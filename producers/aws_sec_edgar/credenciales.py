"""Carga las credenciales del SP en AWS Secrets Manager para la Lambda de entrega (regla 05).

Crea un secreto OAuth nuevo del SP propio de este productor, entity360-producer-sec-edgar
(ADR 0002: un SP por productor), y lo guarda como nueva versión del secreto de Secrets Manager
que creó Terraform (infra/aws/sec_edgar). El valor nunca se imprime ni se escribe a disco.

Uso (raíz del repo; perfil de Databricks del usuario y perfil AWS tesseract):
    .venv\\Scripts\\python.exe producers\\aws_sec_edgar\\credenciales.py cargar [--dias 90]
    .venv\\Scripts\\python.exe producers\\aws_sec_edgar\\credenciales.py verificar
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import boto3

RAIZ = Path(__file__).resolve().parents[2]
PERFIL_DBX = "entity360-free"
SECRETO = "entity360/databricks/producer-sec-edgar"


def cli(*args: str) -> dict:
    r = subprocess.run(["databricks", *args, "-p", PERFIL_DBX, "-o", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"databricks {args[0]} falló: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def cliente():
    return boto3.Session(profile_name="tesseract", region_name="us-east-1").client("secretsmanager")


def cargar(dias: int) -> int:
    # Primero validar el acceso a Secrets Manager: si falla acá, no se crea un secreto del SP huérfano.
    sm = cliente()
    sm.describe_secret(SecretId=SECRETO)
    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    host = cli("auth", "describe")["details"]["host"]
    nuevo = cli("service-principal-secrets-proxy", "create", str(salidas["producer_sec_edgar_sp_id"]),
                "--lifetime", f"{dias * 86400}s")
    valor = {"host": host, "client_id": salidas["producer_sec_edgar_sp_application_id"], "client_secret": nuevo["secret"]}
    r = sm.put_secret_value(SecretId=SECRETO, SecretString=json.dumps(valor))
    print(f"nueva versión de {SECRETO}: {r['VersionId']}; secreto del SP vence {nuevo.get('expire_time')} "
          f"(id {nuevo['id'][:8]}…)")
    return verificar()


def verificar() -> int:
    v = json.loads(cliente().get_secret_value(SecretId=SECRETO)["SecretString"])
    faltan = [k for k in ("host", "client_id", "client_secret") if not v.get(k)]
    print("claves presentes: " + ", ".join(k for k in v if v.get(k)))
    return 1 if faltan else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["cargar", "verificar"])
    ap.add_argument("--dias", type=int, default=90)
    a = ap.parse_args()
    return cargar(a.dias) if a.comando == "cargar" else verificar()


if __name__ == "__main__":
    sys.exit(main())
