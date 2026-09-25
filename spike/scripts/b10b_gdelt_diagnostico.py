"""Spike B.10b: diagnóstico de falso negativo en GDELT (GKG, V2Organizations).

B.10 encontró solo "mercadolibre" en un día. Esta query busca patrones amplios (nombres en
inglés, sin sufijos societarios, nombres cortos) y devuelve CÓMO escribe GDELT cada
organización que matchea, con cantidad de documentos, para ver si el universo aparece con
otra forma.

Guardarraíles (D12): dry run primero; solo se ejecuta si el estimado es <= 100 MiB (lo
esperado es ~50 MB); maximum_bytes_billed = 1 GiB.

Uso:
    $env:GCP_PROJECT_ID = "<GCP_PROJECT_ID>"
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\b10b_gdelt_diagnostico.py [--dia 2026-09-23]
"""

import argparse
import json
import os
import sys
import time

from google.cloud import bigquery

EJECUTAR_SI_HASTA = 100 * 1024**2
TOPE_FACTURADO = 1024**3

# Variantes: castellano, inglés, cortas, sin sufijos.
PATRONES = [
    "ypf", "yacimientos petroliferos", "pampa", "galicia", "macro", "telecom argentina",
    "mercadolibre", "mercado libre", "edenor", "transportadora de gas", "gas transporter",
    "loma negra", "globant", "vista energy", "vista oil", "central puerto", "supervielle",
    "bbva argentina", "bbva frances", "cresud", "irsa", "pluspetrol",
]

SQL = """
SELECT org, COUNT(*) AS documentos
FROM (
  SELECT DISTINCT GKGRECORDID, LOWER(TRIM(REGEXP_EXTRACT(o, r'^([^,]+)'))) AS org
  FROM `gdelt-bq.gdeltv2.gkg_partitioned`, UNNEST(SPLIT(V2Organizations, ';')) AS o
  WHERE _PARTITIONTIME = TIMESTAMP(@dia)
    AND REGEXP_CONTAINS(LOWER(V2Organizations), @regex)
)
WHERE REGEXP_CONTAINS(org, @regex)
GROUP BY org
ORDER BY documentos DESC
LIMIT 60
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dia", default="2026-09-23")
    args = ap.parse_args()
    regex = "(" + "|".join(p.replace(" ", r"\s+") for p in PATRONES) + ")"

    c = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    params = [bigquery.ScalarQueryParameter("dia", "STRING", args.dia),
              bigquery.ScalarQueryParameter("regex", "STRING", regex)]
    dry = c.query(SQL, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                                          query_parameters=params))
    est = dry.total_bytes_processed
    print(f"día {args.dia} | patrones: {len(PATRONES)} (sin \\b: subcadena)")
    print(f"dry run: {est / 1024**2:,.1f} MiB estimados (se ejecuta si <= {EJECUTAR_SI_HASTA / 1024**2:,.0f} MiB)")
    if est > EJECUTAR_SI_HASTA:
        print("NO SE EJECUTA: el estimado supera lo esperado.")
        return 1

    t0 = time.perf_counter()
    job = c.query(SQL, job_config=bigquery.QueryJobConfig(query_parameters=params,
                                                          maximum_bytes_billed=TOPE_FACTURADO))
    filas = [dict(f) for f in job.result()]
    print(f"procesados {job.total_bytes_processed / 1024**2:,.1f} MiB | facturados "
          f"{(job.total_bytes_billed or 0) / 1024**2:,.1f} MiB | {time.perf_counter() - t0:.1f} s")
    print(f"{len(filas)} formas distintas de organización:")
    for f in filas:
        print(f"  {f['documentos']:>5}  {f['org']}")
    print("\n=== resumen JSON ===")
    print(json.dumps({"dia": args.dia, "bytes_estimados": est, "bytes_procesados": job.total_bytes_processed,
                      "filas": filas}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
