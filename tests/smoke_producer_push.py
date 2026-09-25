"""Smoke test de la fase 1: el SP de productores puede empujar al volume con OAuth M2M.

1. Pide un access token con client credentials (/oidc/v1/token).
2. PUT de un registro real de GLEIF (CC0) a /Volumes/entity360/landing/raw/_smoke/ — fuera de
   las carpetas <fuente>/ del contrato de landing, para que Auto Loader no lo tome.
3. GET del mismo archivo y comparación del sha256.
4. Control negativo de escritura: el SP no puede crear otro volume (regla 03: solo escribe
   en landing.raw).
5. Informativo: lectura de gold, heredada de "account users" (docs/adr/0001).

Credenciales solo en el entorno (nunca a disco): DATABRICKS_HOST, DATABRICKS_CLIENT_ID,
DATABRICKS_CLIENT_SECRET.

Uso:
    python tests/smoke_producer_push.py
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import requests

DESTINO = "/Volumes/entity360/landing/raw/_smoke"


def main() -> int:
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    r = requests.post(f"{host}/oidc/v1/token",
                      auth=(os.environ["DATABRICKS_CLIENT_ID"], os.environ["DATABRICKS_CLIENT_SECRET"]),
                      data={"grant_type": "client_credentials", "scope": "all-apis"}, timeout=60)
    r.raise_for_status()
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("1. token OAuth M2M: OK")

    g = requests.get("https://api.gleif.org/api/v1/lei-records",
                     params={"filter[entity.legalAddress.country]": "AR", "page[size]": 1},
                     headers={"Accept": "application/vnd.api+json"}, timeout=60)
    g.raise_for_status()
    datos = json.dumps(g.json()["data"][0], ensure_ascii=False).encode("utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ruta = f"{DESTINO}/smoke_{ts}.jsonl"

    put = requests.put(f"{host}/api/2.0/fs/files{ruta}", params={"overwrite": "false"},
                       headers={**auth, "Content-Type": "application/octet-stream"}, data=datos, timeout=60)
    print(f"2. PUT {ruta} -> HTTP {put.status_code}")
    if not put.ok:
        print(put.text[:300])
        return 1

    get = requests.get(f"{host}/api/2.0/fs/files{ruta}", headers=auth, timeout=60)
    ok = get.ok and hashlib.sha256(get.content).digest() == hashlib.sha256(datos).digest()
    print(f"3. GET -> HTTP {get.status_code}, sha256 coincide: {ok}")

    # Regla 03: el SP solo puede escribir en el volume. Crear otro volume tiene que fallar.
    neg = requests.post(f"{host}/api/2.1/unity-catalog/volumes", headers=auth, timeout=60,
                        json={"catalog_name": "entity360", "schema_name": "landing",
                              "name": "smoke_no_deberia_existir", "volume_type": "MANAGED"})
    neg_ok = neg.status_code in (401, 403)
    print(f"4. control negativo de escritura (crear volume) -> HTTP {neg.status_code}: "
          f"{'denegado, OK' if neg_ok else 'PERMITIDO, revisar grants'}")

    # Informativo (docs/adr/0001): el SP es miembro de "account users" y hereda la lectura de gold.
    info = requests.get(f"{host}/api/2.1/unity-catalog/schemas/entity360.gold", headers=auth, timeout=60)
    print(f"5. info: lectura de metadata de gold -> HTTP {info.status_code} "
          f"({'hereda de account users, ver ADR 0001' if info.ok else 'sin acceso'})")
    return 0 if ok and neg_ok else 1


if __name__ == "__main__":
    sys.exit(main())
