"""Secreto OAuth del SP entity360-producer-gdelt -> GitHub Secrets (ADR 0002, ADR 0003).

Crea un secreto nuevo del SP y lo guarda con su client_id como secretos del repo, con `gh secret
set` por stdin (nunca se imprime ni va a disco). Valida el acceso a GitHub **antes** de crear el
secreto, para no dejar huérfanos.

Secretos del repo que escribe: GDELT_DATABRICKS_CLIENT_ID, GDELT_DATABRICKS_CLIENT_SECRET.
Usa además DATABRICKS_HOST (compartido, lo carga el de enriquecimiento) y los de WIF
(GCP_WIF_PROVIDER, GCP_SERVICE_ACCOUNT, GCP_PROJECT_ID), que salen de infra/gcp:
docs/manual-steps.md §9.

Uso (desde la raíz del repo, con `gh auth login` y el perfil de Databricks del usuario):
    .venv\\Scripts\\python.exe producers\\gcp_gdelt\\credenciales.py cargar [--dias 90]
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PERFIL = "entity360-free"


def cli(*args: str) -> dict:
    r = subprocess.run(["databricks", *args, "-p", PERFIL, "-o", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"databricks {args[0]} falló: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def gh(*args: str, entrada: str | None = None) -> str:
    r = subprocess.run(["gh", *args], input=entrada, capture_output=True, text=True, cwd=RAIZ)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} falló: {r.stderr.strip()[:300]}")
    return r.stdout


def cargar(dias: int) -> int:
    if not shutil.which("gh"):
        print("Falta la CLI de GitHub (winget install GitHub.cli; gh auth login).")
        return 2
    existentes = gh("secret", "list")  # 1. valida auth y permisos sobre el repo antes de crear nada
    if "DATABRICKS_HOST" not in existentes:
        print("Falta el secreto DATABRICKS_HOST (lo carga producers/container_enrichment/credenciales.py).")
        return 2

    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    secreto = cli("service-principal-secrets-proxy", "create", str(salidas["producer_gdelt_sp_id"]),
                  "--lifetime", f"{dias * 86400}s")                                        # 2. secreto del SP
    valores = {"GDELT_DATABRICKS_CLIENT_ID": salidas["producer_gdelt_sp_application_id"],
               "GDELT_DATABRICKS_CLIENT_SECRET": secreto["secret"]}
    for nombre, valor in valores.items():                                                  # 3. GitHub Secrets
        gh("secret", "set", nombre, entrada=valor)
    print(f"secretos del repo actualizados: {', '.join(valores)}")
    print(f"secreto del SP {secreto['id'][:8]}… vence {secreto.get('expire_time')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["cargar"])
    ap.add_argument("--dias", type=int, default=90, help="vida útil del secreto OAuth del SP")
    return cargar(ap.parse_args().dias)


if __name__ == "__main__":
    sys.exit(main())
