"""Credenciales del extractor CDC en el Administrador de credenciales de Windows (keyring).

Nada de esto va a disco ni se imprime. Servicio de keyring: "entity360-cdc-extractor".

    databricks_host       URL del workspace (no es secreto, pero viaja junto con el resto)
    databricks_client_id  application_id del SP entity360-producer
    databricks_secret     secreto OAuth del SP (vida útil acotada, ver --dias)
    sql_password          contraseña del login de SQL Server cdc_extractor (solo lectura)

Uso (desde la raíz del repo, con el perfil de Databricks del usuario y legacy/.env):
    .venv\\Scripts\\python.exe producers\\cdc_extractor\\credenciales.py configurar [--dias 90]
    .venv\\Scripts\\python.exe producers\\cdc_extractor\\credenciales.py verificar
"""

import argparse
import json
import secrets
import string
import subprocess
import sys
from pathlib import Path

import keyring
import pymssql

SERVICIO = "entity360-cdc-extractor"
CLAVES = ["databricks_host", "databricks_client_id", "databricks_secret", "sql_password"]
RAIZ = Path(__file__).resolve().parents[2]
PERFIL = "entity360-free"


def cli(*args: str) -> dict:
    r = subprocess.run(["databricks", *args, "-p", PERFIL, "-o", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"databricks {args[0]} falló: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def contrasena() -> str:
    alfabeto = string.ascii_letters + string.digits
    return (secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase)
            + secrets.choice(string.digits) + "-" + "".join(secrets.choice(alfabeto) for _ in range(24)))


def crear_login_sql(pw: str) -> None:
    """Login de solo lectura para el extractor (no usa sa). Idempotente: si existe, cambia la contraseña."""
    env = dict(l.split("=", 1) for l in (RAIZ / "legacy" / ".env").read_text(encoding="utf-8").splitlines() if "=" in l)
    con = pymssql.connect(server="127.0.0.1", port=1433, user="sa", password=env["MSSQL_SA_PASSWORD"],
                          database="entity360_erp", autocommit=True)
    cur = con.cursor()
    literal = pw.replace("'", "''")  # CREATE/ALTER LOGIN no aceptan parámetros
    cur.execute(f"""
        IF SUSER_ID('cdc_extractor') IS NULL
            CREATE LOGIN cdc_extractor WITH PASSWORD = '{literal}', CHECK_POLICY = ON, DEFAULT_DATABASE = entity360_erp;
        ELSE
            ALTER LOGIN cdc_extractor WITH PASSWORD = '{literal}';
        IF USER_ID('cdc_extractor') IS NULL
            CREATE USER cdc_extractor FOR LOGIN cdc_extractor;
        GRANT SELECT ON SCHEMA::cdc TO cdc_extractor;
        GRANT SELECT ON SCHEMA::erp TO cdc_extractor;
    """)
    con.close()


def configurar(dias: int) -> int:
    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    host = cli("auth", "describe")["details"]["host"]
    secreto = cli("service-principal-secrets-proxy", "create", str(salidas["producer_sp_id"]),
                  "--lifetime", f"{dias * 86400}s")
    pw = contrasena()
    crear_login_sql(pw)
    valores = {"databricks_host": host, "databricks_client_id": salidas["producer_sp_application_id"],
               "databricks_secret": secreto["secret"], "sql_password": pw}
    for k, v in valores.items():
        keyring.set_password(SERVICIO, k, v)
    print(f"credenciales guardadas en el Administrador de credenciales ({SERVICIO}); "
          f"secreto del SP vence {secreto.get('expire_time')}")
    return verificar()


def verificar() -> int:
    faltan = [k for k in CLAVES if not keyring.get_password(SERVICIO, k)]
    print(f"backend de keyring: {type(keyring.get_keyring()).__name__}")
    print("claves presentes: " + ", ".join(k for k in CLAVES if k not in faltan))
    if faltan:
        print("FALTAN: " + ", ".join(faltan))
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["configurar", "verificar"])
    ap.add_argument("--dias", type=int, default=90, help="vida útil del secreto OAuth del SP")
    a = ap.parse_args()
    return configurar(a.dias) if a.comando == "configurar" else verificar()


if __name__ == "__main__":
    sys.exit(main())
