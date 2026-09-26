"""Diagnóstico para armar el diccionario de alias (alias.json): cómo escribe GDELT a cada emisor.

GDELT traduce palabra por palabra los nombres de artículos no ingleses ("Banco Galicia" -> "bank
galicia", spike B.10b). Esta consulta busca patrones amplios (castellano, inglés, traducciones y
nombres cortos) en V2Organizations durante N días y devuelve cada forma distinta con su cantidad de
documentos. Con eso se curan a mano los alias: forma completa e inequívoca, nunca nombres cortos
ambiguos ("galicia" es la región de España; "macro" es Macron o macroeconomía).

Guardarraíles (D12): dry run primero; se ejecuta solo si el estimado es <= 500 MiB (lo esperado es
~28 MiB por día); maximum_bytes_billed = 1 GiB.

Uso (ADC del usuario, proyecto sandbox):
    $env:GCP_PROJECT_ID = "<GCP_PROJECT_ID>"
    spike\\.venv\\Scripts\\python.exe producers\\gcp_gdelt\\diagnostico_alias.py --desde 2026-09-19 --hasta 2026-09-25
"""

import argparse
import json
import os
import sys
import time

from google.cloud import bigquery

EJECUTAR_SI_HASTA = 500 * 1024**2
TOPE_FACTURADO = 1024**3

# Por emisor de producers/aws_sec_edgar/universo.json: castellano, inglés y traducciones literales.
PATRONES = [
    "ypf", "yacimientos petroliferos", "fields petroleum", "oilfields fiscal",
    "galicia", "pampa", "macro", "telecom argentina", "telecom of argentina",
    "transportadora de gas", "gas transporter", "transporter of gas", "carrier gas",
    "edenor", "central puerto", "central port", "port central", "supervielle",
    "bbva argentina", "bbva frances", "bbva french", "bank french", "cresud", "irsa",
    "loma negra", "loma black", "vista energy", "vista oil", "mercadolibre", "mercado libre",
    "free market", "globant",
]

SQL = """
SELECT org, COUNT(*) AS documentos, COUNT(DISTINCT dia) AS dias
FROM (
  SELECT DISTINCT GKGRECORDID, DATE(_PARTITIONTIME) AS dia,
         LOWER(TRIM(REGEXP_EXTRACT(o, r'^([^,]+)'))) AS org
  FROM `gdelt-bq.gdeltv2.gkg_partitioned`, UNNEST(SPLIT(V2Organizations, ';')) AS o
  WHERE _PARTITIONTIME BETWEEN TIMESTAMP(@desde) AND TIMESTAMP(@hasta)
    AND REGEXP_CONTAINS(LOWER(V2Organizations), @regex)
)
WHERE REGEXP_CONTAINS(org, @regex)
GROUP BY org
ORDER BY documentos DESC
LIMIT 400
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    a = ap.parse_args()
    regex = "(" + "|".join(p.replace(" ", r"\s+") for p in PATRONES) + ")"
    c = bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location="US")
    params = [bigquery.ScalarQueryParameter("desde", "STRING", a.desde),
              bigquery.ScalarQueryParameter("hasta", "STRING", a.hasta),
              bigquery.ScalarQueryParameter("regex", "STRING", regex)]
    est = c.query(SQL, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                                          query_parameters=params)).total_bytes_processed
    print(f"días {a.desde} a {a.hasta} | {len(PATRONES)} patrones (subcadena)")
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
    print(f"{len(filas)} formas distintas (documentos | días | forma):")
    for f in filas:
        print(f"  {f['documentos']:>5} | {f['dias']} | {f['org']}")
    print("\n=== resumen JSON ===")
    print(json.dumps({"desde": a.desde, "hasta": a.hasta, "bytes_procesados": job.total_bytes_processed,
                      "filas": filas}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
