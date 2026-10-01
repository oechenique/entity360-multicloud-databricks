"""DAG de convergencia (regla 10): el plano de control de lo que vive fuera de Databricks.

1. extraer_cdc: el extractor CDC del legacy (SQL Server en la PC) empuja sus cambios al landing.
2. llegada_<fuente>: un sensor por fuente sobre los manifests del landing. Si el último lote es más
   viejo que el warn_after de su frescura en dbt, espera; al vencer el timeout la fuente queda
   `skipped` como atrasada, se alerta y el resto sigue (un proveedor roto no frena la plataforma).
3. contratos: Soda Core sobre los lotes sin veredicto (contracts/verificar.py). Un lote en
   cuarentena no frena el DAG: queda apartado y alertado; Bronze exige el veredicto (ADR 0006).
4. medallion: dispara el job entity360-medallion (bronze -> silver -> resolucion) y espera.
5. dbt_gold: los modelos Gold con Cosmos, un task por modelo y sus tests después de cada uno.
6. frescura: dbt source freshness (fuentes y resolución). Un `error` falla la tarea y alerta.
7. Snowflake (fase 9, Camino A), después de dbt_gold: snowflake_refrescar (metadata de las tablas de
   ENTITY360_UC) -> snowflake_grants (lectura de dbt y los modelers) -> dbt_marts -> dbt_marts_tests.
   Rol ENTITY360_SYNC (dueño de la base, sin ACCOUNTADMIN) para las dos primeras; ENTITY360_DBT para dbt.
   Gold es incremental con INSERT OVERWRITE: el UUID de las tablas no cambia y el refresco alcanza.
8. resultado: la hoja del DAG; manda el aviso de cierre por Telegram (falla: callback del DAG). Corre solo si ni dbt_gold, ni frescura, ni las tareas de Snowflake
   fallaron; si no, queda upstream_failed y la corrida termina `failed`. Sin ella, la única hoja era
   frescura (all_done), y una corrida con dbt caído figuraba `success` (2026-09-29).

Credenciales: variables de entorno del container (airflow/levantar.ps1, ADR 0007). Nada en el DAG.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pendulum
from airflow.providers.databricks.operators.databricks import DatabricksRunNowOperator
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.python import PythonSensor
from airflow.sdk import DAG
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entity360 import landing, notificar  # noqa: E402

RAIZ = Path(os.environ.get("E360_RAIZ", "/opt/entity360"))
VENVS = Path("/opt/airflow/venvs")
PERFILES = RAIZ / "airflow_config"
UMBRALES = landing.umbrales(RAIZ / "dbt" / "models" / "sources.yml")


def alertar(titulo: str, texto: str) -> None:
    sys.path.insert(0, str(RAIZ / "contracts"))
    import alertas
    alertas.enviar(titulo, texto)


def al_fallar(context) -> None:
    ti = context["task_instance"]
    alertar(f"entity360: falló {ti.task_id}", f"DAG {ti.dag_id}, corrida {context['run_id']}. Log: {ti.log_url}")


def al_saltear(context) -> None:
    ti = context["task_instance"]
    fuente = ti.task_id.removeprefix("llegada_")
    alertar(f"entity360: fuente atrasada ({fuente})",
            f"Sin lotes nuevos en más de {UMBRALES[fuente]} (warn_after de su frescura). El resto del DAG sigue.")


def cierre_ok(**context) -> None:
    dr = context["dag_run"]
    alertar(*notificar.mensaje("ok", dr.dag_id, dr.run_id, dr.start_date))


def cierre_falla(context) -> None:
    """on_failure_callback del DAG: `resultado` no corre cuando algo falló."""
    dr = context["dag_run"]
    try:
        fallidas = [ti.task_id for ti in dr.get_task_instances(state=["failed", "upstream_failed"])]
    except Exception:          # noqa: BLE001 - sin acceso a la base desde el callback: mensaje sin lista
        fallidas = None
    alertar(*notificar.mensaje("falla", dr.dag_id, dr.run_id, dr.start_date, fallidas))


def llego(fuente: str) -> bool:
    ultimo = landing.Landing().ultimo_manifest(fuente)
    print(f"{fuente}: último manifest {ultimo or '-'}; umbral {UMBRALES[fuente]}")
    return ultimo is not None and ultimo >= datetime.now(timezone.utc) - UMBRALES[fuente]


with DAG(
    dag_id="entity360_convergencia",
    description="CDC -> llegada -> contratos (Soda) -> job de Databricks -> dbt (Cosmos) -> frescura y Snowflake",
    schedule="45 8 * * *",   # el horario del schedule del job, pausado desde el ADR 0006
    start_date=pendulum.datetime(2026, 9, 27, tz="America/Argentina/Buenos_Aires"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5), "on_failure_callback": al_fallar},
    tags=["entity360"],
    on_failure_callback=cierre_falla,
    doc_md=__doc__,
) as dag:
    extraer_cdc = BashOperator(
        task_id="extraer_cdc",
        bash_command=f"python {RAIZ}/cdc_extractor/extractor.py",
        execution_timeout=timedelta(minutes=15),
    )

    sensores = {
        fuente: PythonSensor(
            task_id=f"llegada_{fuente}",
            python_callable=llego,
            op_args=[fuente],
            mode="reschedule",           # libera el slot entre chequeos
            poke_interval=timedelta(minutes=5),
            timeout=timedelta(minutes=30),
            soft_fail=True,              # atrasada = skipped + alerta, no falla el DAG
            on_skipped_callback=al_saltear,
            retries=0,
            # El CDC se mira aunque el extractor haya fallado (el legacy apagado es un atraso).
            trigger_rule="all_done",
        )
        for fuente in landing.FUENTES
    }
    extraer_cdc >> sensores["sqlserver_cdc"]

    contratos = BashOperator(
        task_id="contratos",
        bash_command=f"{VENVS}/soda/bin/python {RAIZ}/contracts/verificar.py --pendientes",
        trigger_rule="all_done",         # sensores atrasados (skipped) o CDC caído no lo frenan
        execution_timeout=timedelta(minutes=30),
    )

    medallion = DatabricksRunNowOperator(
        task_id="medallion",
        databricks_conn_id="databricks_default",
        job_id=os.environ.get("E360_MEDALLION_JOB_ID"),
        wait_for_termination=True,
        polling_period_seconds=60,
        execution_timeout=timedelta(hours=1),
        retries=0,                        # el job ya tiene sus reintentos por tarea (medallion.tf)
    )

    dbt_gold = DbtTaskGroup(
        group_id="dbt_gold",
        project_config=ProjectConfig(RAIZ / "dbt"),
        profile_config=ProfileConfig(profile_name="entity360", target_name="airflow",
                                     profiles_yml_filepath=PERFILES / "profiles.yml"),
        execution_config=ExecutionConfig(dbt_executable_path=str(VENVS / "dbt" / "bin" / "dbt")),
        # Un test que mira dos modelos (relationships de un fct hacia dim_entity) va en su propia tarea,
        # después de los dos: si no, Cosmos lo cuelga de dim_entity y corre mientras el fct se recrea
        # (primera corrida, 2026-09-27: TABLE_OR_VIEW_NOT_FOUND y reintento).
        render_config=RenderConfig(select=["path:models/gold"], should_detach_multiple_parents_tests=True),
        operator_args={"install_deps": False},
    )

    frescura = BashOperator(
        task_id="frescura",
        bash_command=(f"cd {RAIZ}/dbt && {VENVS}/dbt/bin/dbt source freshness --profiles-dir {PERFILES} "
                      "--target airflow --target-path /tmp/dbt-frescura --log-path /tmp/dbt-frescura"),
        trigger_rule="all_done",         # también cuando dbt_gold falló: dice qué fuente está atrasada
        execution_timeout=timedelta(minutes=10),
    )

    snowflake_refrescar, snowflake_grants = (
        BashOperator(
            task_id=f"snowflake_{accion}",
            bash_command=f"{VENVS}/dbt/bin/python {RAIZ}/snowflake/integracion.py {accion} --conexion entorno",
            execution_timeout=timedelta(minutes=10),
        )
        for accion in ("refrescar", "grants")
    )
    dbt_snowflake = (f"cd {RAIZ}/dbt && {VENVS}/dbt/bin/dbt {{}} --select marts --profiles-dir {PERFILES} "
                     "--target snowflake --target-path /tmp/dbt-marts --log-path /tmp/dbt-marts")
    dbt_marts, dbt_marts_tests = (
        BashOperator(task_id=task_id, bash_command=dbt_snowflake.format(comando),
                     execution_timeout=timedelta(minutes=15))
        for task_id, comando in (("dbt_marts", "run"), ("dbt_marts_tests", "test"))
    )

    # Hoja del DAG y aviso de cierre por Telegram (notificar.py): corre solo si no falló nada.
    resultado = PythonOperator(task_id="resultado", python_callable=cierre_ok, trigger_rule="none_failed",
                               retries=0)

    list(sensores.values()) >> contratos >> medallion >> dbt_gold >> frescura
    dbt_gold >> snowflake_refrescar >> snowflake_grants >> dbt_marts >> dbt_marts_tests
    [dbt_gold, frescura, dbt_marts_tests] >> resultado
