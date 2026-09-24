"""Spike A.1: push de un lote real al UC Volume con la Files API de Databricks.

Baja una muestra chica de GLEIF (entidades argentinas, licencia CC0), la sube siguiendo
el contrato de landing (regla 01) y después sube el _manifest_<ts>.json del lote.

Auth (desde el entorno, nunca se escribe a disco ni se imprime):
- PAT: DATABRICKS_TOKEN.
- OAuth M2M: DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (service principal); se pide
  un access token al endpoint /oidc/v1/token del workspace.
Siempre DATABRICKS_HOST.

Después de subir, relee el archivo de datos con la Files API y compara el sha256.

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


def obtener_token(host: str) -> tuple[str, str]:
    """Devuelve (token, modo). Prioriza OAuth M2M si hay credenciales de service principal."""
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
    if client_id and client_secret:
        resp = requests.post(
            f"{host.rstrip('/')}/oidc/v1/token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials", "scope": "all-apis"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["access_token"], "oauth-m2m"
    return os.environ["DATABRICKS_TOKEN"], "pat"


def verificar(resp: requests.Response) -> None:
    """raise_for_status con el cuerpo del error (sin headers, que llevan el token)."""
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} {resp.request.method}: {resp.text[:500]}")


def get_archivo(host: str, token: str, ruta_volume: str) -> bytes:
    url = f"{host.rstrip('/')}/api/2.0/fs/files{ruta_volume}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=120)
    verificar(resp)
    return resp.content


def put_archivo(host: str, token: str, ruta_volume: str, contenido: bytes) -> int:
    url = f"{host.rstrip('/')}/api/2.0/fs/files{ruta_volume}"
    resp = requests.put(
        url,
        params={"overwrite": "false"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        data=contenido,
        timeout=120,
    )
    verificar(resp)
    return resp.status_code


def main() -> int:
    host = os.environ["DATABRICKS_HOST"]
    token, modo = obtener_token(host)
    print(f"auth: {modo}")

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

    releido = get_archivo(host, token, ruta_datos)
    ok = hashlib.sha256(releido).hexdigest() == manifest["sha256"]
    print(f"GET {ruta_datos} -> {len(releido)} bytes, sha256 coincide: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
