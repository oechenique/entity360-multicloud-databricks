"""Secreto OAuth del SP entity360-producer-enrichment -> GitHub Secrets (ADR 0002).

Crea un secreto nuevo del SP y lo guarda, junto con el host, el client_id y el User-Agent, como
secretos del repo con `gh secret set` (por stdin: nunca se imprime ni va a disco). Valida el acceso
a GitHub **antes** de crear el secreto, para no dejar huérfanos (aprendizaje de la fase 3).

Secretos del repo: DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, USER_AGENT.

Requiere la CLI de GitHub autenticada (`gh auth login`) y el perfil de Databricks del usuario.

Uso (desde la raíz del repo):
    $env:ENRIQUECIMIENTO_USER_AGENT = "entity360 (portfolio) <mail>"
    .venv\\Scripts\\python.exe producers\\container_enrichment\\credenciales.py cargar [--dias 90]
"""

import argparse
import json
import os
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
    ua = os.environ.get("ENRIQUECIMIENTO_USER_AGENT", "")
    if "@" not in ua:
        print("Falta ENRIQUECIMIENTO_USER_AGENT con un contacto (pautas de uso de Wikidata).")
        return 2
    if not shutil.which("gh"):
        print("Falta la CLI de GitHub (winget install GitHub.cli; gh auth login).")
        return 2
    gh("secret", "list")  # 1. valida auth y permisos sobre el repo antes de crear nada

    salidas = {o: v["value"] for o, v in json.loads(
        (RAIZ / "infra" / "databricks" / "terraform.tfstate").read_text(encoding="utf-8"))["outputs"].items()}
    host = cli("auth", "describe")["details"]["host"]
    secreto = cli("service-principal-secrets-proxy", "create", str(salidas["producer_enrichment_sp_id"]),
                  "--lifetime", f"{dias * 86400}s")                                       # 2. secreto del SP
    valores = {"DATABRICKS_HOST": host, "DATABRICKS_CLIENT_ID": salidas["producer_enrichment_sp_application_id"],
               "DATABRICKS_CLIENT_SECRET": secreto["secret"], "USER_AGENT": ua}
    for nombre, valor in valores.items():                                                 # 3. GitHub Secrets
        gh("secret", "set", nombre, entrada=valor)
    print(f"secretos del repo actualizados: {', '.join(valores)}")
    print(f"secreto del SP {secreto['id'][:8]}… vence {secreto.get('expire_time')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["cargar"])
    ap.add_argument("--dias", type=int, default=90, help="vida útil del secreto OAuth del SP")
    a = ap.parse_args()
    return cargar(a.dias)


if __name__ == "__main__":
    sys.exit(main())
