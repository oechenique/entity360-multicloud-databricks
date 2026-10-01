"""Estructura del DAG sin Airflow instalado: se lee el código (ast). Las tareas de Snowflake van después de
dbt_gold, en orden, y `resultado` depende de la última."""

import ast
from pathlib import Path

DAG = Path(__file__).resolve().parents[2] / "airflow" / "dags" / "entity360_convergencia.py"
CODIGO = DAG.read_text(encoding="utf-8")


def cadenas() -> list[list[str]]:
    """Cada sentencia `a >> b >> c` como lista de nombres (las listas [x, y] se aplanan)."""
    out = []
    for nodo in ast.walk(ast.parse(CODIGO)):
        if isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.BinOp) and isinstance(nodo.value.op, ast.RShift):
            pasos, n = [], nodo.value
            while isinstance(n, ast.BinOp):
                pasos.insert(0, n.right)
                n = n.left
            pasos.insert(0, n)
            out.append([ast.unparse(p) for p in pasos])
    return out


def test_snowflake_despues_de_gold_en_orden():
    assert ["dbt_gold", "snowflake_refrescar", "snowflake_grants", "dbt_marts", "dbt_marts_tests"] in cadenas()


def test_resultado_espera_los_tests_de_los_marts():
    assert ["[dbt_gold, frescura, dbt_marts_tests]", "resultado"] in cadenas()
    assert 'EmptyOperator(task_id="resultado", trigger_rule="none_failed")' in CODIGO


def test_snowflake_sin_accountadmin():
    assert "ACCOUNTADMIN" not in CODIGO.split("with DAG(")[1]
    assert "integracion.py {accion} --conexion entorno" in CODIGO
    assert '("dbt_marts", "run"), ("dbt_marts_tests", "test")' in CODIGO
    assert "--target snowflake" in CODIGO
