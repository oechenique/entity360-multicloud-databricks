"""Spike A.1: push de un lote real al UC Volume con la Files API de Databricks.

Baja una muestra chica de GLEIF (entidades argentinas, licencia CC0), la sube siguiendo
el contrato de landing (regla 01) y después sube el _manifest.json del lote.

Auth: lee DATABRICKS_HOST y DATABRICKS_TOKEN del entorno. El token nunca se escribe a
disco ni se imprime.

Uso:
    python spike/scripts/a1_push_files_api.py
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import requests

GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
VOLUME_ROOT = "/Volumes/entity360/landing/raw"
FUENTE = "gleif"
PRODUCER_VERSION = "spike-a1-0.1"


def bajar_muestra_gleif(pais: str = "AR", cantidad: int = 10) -> list[dict]:
    resp = requests.get(
        GLEIF_URL,
        params={"filter[entity.legalAddress.country]": pais, "page[size]": cantidad},
        headers={"Accept": "application/vnd.api+json"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def put_archivo(host: str, token: str, ruta_volume: str, contenido: bytes) -> int:
    url = f"{host.rstrip('/')}/api/2.0/fs/files{ruta_volume}"
    resp = requests.put(
        url,
        params={"overwrite": "false"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        data=contenido,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.status_code


def main() -> int:
    host = os.environ["DATABRICKS_HOST"]
    token = os.environ["DATABRICKS_TOKEN"]

    registros = bajar_muestra_gleif()
    ahora = datetime.now(timezone.utc)
    ts = ahora.strftime("%Y%m%dT%H%M%SZ")
    carpeta = f"{VOLUME_ROOT}/{FUENTE}/ingest_date={ahora:%Y-%m-%d}"

    # JSON Lines: un registro por línea, lo que read_files lee directo.
    datos = "\n".join(json.dumps(r, ensure_ascii=False) for r in registros).encode("utf-8")
    ruta_datos = f"{carpeta}/{FUENTE}_{ts}.jsonl"
    status = put_archivo(host, token, ruta_datos, datos)
    print(f"PUT {ruta_datos} -> HTTP {status} ({len(datos)} bytes)")

    manifest = {
        "fuente": FUENTE,
        "archivo": ruta_datos.rsplit("/", 1)[1],
        "registros": len(registros),
        "sha256": hashlib.sha256(datos).hexdigest(),
        "extraido_utc": ahora.isoformat(),
        "producer_version": PRODUCER_VERSION,
        "origen": GLEIF_URL,
        "licencia": "CC0 1.0 (GLEIF)",
    }
    # Un manifest por lote: el nombre lleva el timestamp para no pisar lotes del mismo día.
    ruta_manifest = f"{carpeta}/_manifest_{ts}.json"
    status = put_archivo(host, token, ruta_manifest, json.dumps(manifest, indent=2).encode("utf-8"))
    print(f"PUT {ruta_manifest} -> HTTP {status}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
