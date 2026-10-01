"""Credenciales de Airflow en el Administrador de credenciales de Windows (keyring). ADR 0007.

Nada de esto va a disco ni se imprime. Servicio de keyring: "entity360-airflow".

    databricks_host       URL del workspace
    databricks_client_id  application_id del SP entity360-orquestador (output orquestador_sp_application_id)
    databricks_secret     secreto OAuth del SP (vida útil acotada, ver --dias)
    warehouse_http_path   http_path del SQL warehouse (dbt)
    medallion_job_id      id del job entity360-medallion

`levantar.ps1` lee estas claves (y las del extractor CDC, servicio "entity360-cdc-extractor") y se las
pasa a docker compose como variables de entorno del proceso: no se escriben en ningún archivo.

Uso (desde la raíz del repo, con el perfil de Databricks del usuario):
    .venv\\Scripts\\python.exe airflow\\credenciales.py configurar [--dias 90]
    .venv\\Scripts\\python.exe airflow\\credenciales.py verificar
    .venv\\Scripts\\python.exe airflow\\credenciales.py entorno      (lo usa levantar.ps1)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import keyring

SERVICIO = "entity360-airflow"
CLAVES = ["databricks_host", "databricks_client_id", "databricks_secret", "warehouse_http_path", "medallion_job_id"]
SERVICIO_TELEGRAM = "entity360-telegram"          # opcional: bot_token y chat_id (docs/manual-steps.md §10)
CLAVES_TELEGRAM = ["bot_token", "chat_id"]
SERVICIO_CDC = "entity360-cdc-extractor"
CLAVES_CDC = ["databricks_host", "databricks_client_id", "databricks_secret", "sql_password"]
RAIZ = Path(__file__).resolve().parents[1]
PERFIL = "entity360-free"
WAREHOUSE = "Serverless Starter Warehouse"


def cli(*args: str) -> dict | list:
    r = subprocess.run(["databricks", *args, "-p", PERFIL, "-o", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"databricks {args[0]} falló: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def configurar(dias: int) -> int:
    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    host = cli("auth", "describe")["details"]["host"]
    wh = next(w for w in cli("warehouses", "list") if w["name"] == WAREHOUSE)
    secreto = cli("service-principal-secrets-proxy", "create", str(salidas["orquestador_sp_id"]),
                  "--lifetime", f"{dias * 86400}s")
    valores = {"databricks_host": host.rstrip("/"), "databricks_client_id": salidas["orquestador_sp_application_id"],
               "databricks_secret": secreto["secret"], "warehouse_http_path": f"/sql/1.0/warehouses/{wh['id']}",
               "medallion_job_id": str(salidas["medallion_job_id"])}
    for k, v in valores.items():
        keyring.set_password(SERVICIO, k, v)
    print(f"credenciales guardadas en el Administrador de credenciales ({SERVICIO}); "
          f"secreto del SP vence {secreto.get('expire_time')}")
    return verificar()


def verificar() -> int:
    ok = 0
    for servicio, claves in ((SERVICIO, CLAVES), (SERVICIO_CDC, CLAVES_CDC)):
        faltan = [k for k in claves if not keyring.get_password(servicio, k)]
        print(f"{servicio}: " + ("completo" if not faltan else "FALTAN " + ", ".join(faltan)))
        ok |= bool(faltan)
    return ok


def cuenta_snowflake(archivo: Path = Path.home() / ".snowflake" / "connections.toml") -> str:
    """Account identifier de la conexión `entity360` (snowflake/cuenta.py conexiones). Vacío si no hay."""
    if not archivo.exists():
        return ""
    import tomllib
    return tomllib.loads(archivo.read_text(encoding="utf-8")).get("entity360", {}).get("account", "")


def telegram() -> dict[str, str]:
    """TELEGRAM_* del llavero, solo si están las dos claves: sin bot, ninguna (las alertas van a stderr,
    contracts/alertas.py). levantar.ps1 no puede cargar una variable vacía."""
    t = {k: keyring.get_password(SERVICIO_TELEGRAM, k) for k in CLAVES_TELEGRAM}
    if not all(t.values()):
        return {}
    return {"TELEGRAM_BOT_TOKEN": t["bot_token"], "TELEGRAM_CHAT_ID": t["chat_id"]}


def entorno() -> int:
    """Una línea NOMBRE=valor por variable, para que levantar.ps1 las cargue en su proceso."""
    a = {k: keyring.get_password(SERVICIO, k) for k in CLAVES}
    c = {k: keyring.get_password(SERVICIO_CDC, k) for k in CLAVES_CDC}
    if not all(a.values()) or not all(c.values()):
        print("faltan credenciales: correr `credenciales.py verificar`", file=sys.stderr)
        return 1
    variables = {
        "E360_DATABRICKS_HOST": a["databricks_host"],
        "E360_ORQ_CLIENT_ID": a["databricks_client_id"],
        "E360_ORQ_CLIENT_SECRET": a["databricks_secret"],
        "E360_WAREHOUSE_HTTP_PATH": a["warehouse_http_path"],
        "E360_MEDALLION_JOB_ID": a["medallion_job_id"],
        "CDC_DATABRICKS_HOST": c["databricks_host"],
        "CDC_DATABRICKS_CLIENT_ID": c["databricks_client_id"],
        "CDC_DATABRICKS_SECRET": c["databricks_secret"],
        "CDC_SQL_PASSWORD": c["sql_password"],
        # Fase 9: el account identifier vive solo en ~/.snowflake (no es un secreto, pero identifica).
        "E360_SNOWFLAKE_ACCOUNT": cuenta_snowflake(),
    }
    variables.update(telegram())
    for k, v in variables.items():
        print(f"{k}={v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["configurar", "verificar", "entorno"])
    ap.add_argument("--dias", type=int, default=90, help="vida útil del secreto OAuth del SP")
    a = ap.parse_args()
    return {"configurar": lambda: configurar(a.dias), "verificar": verificar, "entorno": entorno}[a.comando]()


if __name__ == "__main__":
    sys.exit(main())
