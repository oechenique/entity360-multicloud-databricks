"""Container de enriquecimiento (regla 07): OpenSanctions + Wikidata -> UC Volume.

Cada fuente es un lote independiente con su manifest (`opensanctions`, `wikidata`): si una falla,
la otra igual se publica, y el proceso termina con error para que el workflow lo muestre.

Variables de entorno:
    USER_AGENT                  contacto para los endpoints (pautas de Wikidata y OpenSanctions)
    DATABRICKS_HOST             URL del workspace
    DATABRICKS_CLIENT_ID        application_id del SP entity360-producer-enrichment
    DATABRICKS_CLIENT_SECRET    secreto OAuth del SP (o DATABRICKS_TOKEN para pruebas manuales)

Uso:
    python main.py [--fuentes opensanctions,wikidata] [--solo-leer]
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import landing
import opensanctions
import wikidata

VERSION = "enrichment-1.0"
UNIVERSO_SEC = Path(__file__).resolve().parent / "universo_sec.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuentes", default="opensanctions,wikidata")
    ap.add_argument("--solo-leer", action="store_true", help="extrae y resume, no empuja")
    a = ap.parse_args()
    ua = os.environ.get("USER_AGENT", "")
    if "@" not in ua:
        print("Falta USER_AGENT con un contacto (pautas de uso de Wikidata).")
        return 2

    vol = None if a.solo_leer else landing.Volume()
    emisores = json.loads(UNIVERSO_SEC.read_text(encoding="utf-8"))["emisores"]
    extractores = {
        "opensanctions": lambda: opensanctions.extraer(ua),
        "wikidata": lambda: wikidata.extraer(ua, emisores),
    }
    fallas = 0
    for fuente in a.fuentes.split(","):
        t0 = time.perf_counter()
        try:
            filas, extra = extractores[fuente]()
            r = landing.publicar(vol, fuente, VERSION, filas, extra)
            print(f"{fuente}: {r} ({time.perf_counter() - t0:,.1f} s)")
        except Exception:
            fallas += 1
            print(f"{fuente}: FALLÓ ({time.perf_counter() - t0:,.1f} s)")
            # Los errores de conexión traen el hostname del workspace: no va a los logs (principio 9).
            host = urlparse(os.environ.get("DATABRICKS_HOST", "")).netloc
            detalle = traceback.format_exc()
            print(detalle.replace(host, "<WORKSPACE_HOST>") if host else detalle, file=sys.stderr)
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
