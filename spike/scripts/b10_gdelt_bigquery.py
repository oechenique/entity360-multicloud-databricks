"""Spike B.10: GDELT en BigQuery (modo sandbox, sin billing).

Reglas de la regla 02, punto 10:
- Solo tablas particionadas, siempre con filtro de partición (_PARTITIONTIME).
- Dry run antes de cada query: si los bytes estimados superan el tope, NO se ejecuta.
- Además, maximum_bytes_billed en la query real (BigQuery la corta si se pasa).

Mide, para UN día de partición, cuántas menciones de organizaciones del universo aparecen
en GKG (V2Organizations) y en Events (Actor1Name/Actor2Name), comparando bytes escaneados.

Auth: credenciales de usuario (Application Default Credentials). Proyecto: GCP_PROJECT_ID.

Uso:
    $env:GCP_PROJECT_ID = "<GCP_PROJECT_ID>"
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\b10_gdelt_bigquery.py [--dia 2026-09-24] [--solo-dry-run]
"""

import argparse
import json
import os
import sys
import time

from google.cloud import bigquery

# Guardarraíl cerca del consumo esperado (~50 MB por día de GKG), no del máximo de la cuota:
# si una query estima o factura más de 1 GiB, algo cambió (falta el filtro, otra tabla) y se corta.
TOPE_BYTES = 1 * 1024**3  # 1 GiB por query (D12)

# Organizaciones del universo, como las escribe GDELT (minúsculas en GKG, mayúsculas en Events).
ORGS = ["ypf", "pampa energia", "banco macro", "telecom argentina", "mercadolibre", "mercado libre",
        "grupo financiero galicia", "banco galicia", "edenor", "transportadora de gas del sur",
        "loma negra", "globant", "vista energy", "central puerto", "grupo supervielle",
        "bbva argentina", "cresud", "irsa", "pluspetrol"]


def regex_orgs() -> str:
    return r"(?i)\b(" + "|".join(o.replace(" ", r"\s+") for o in ORGS) + r")\b"


CONSULTAS = {
    "gkg_organizaciones": """
SELECT org, COUNT(*) AS menciones, ROUND(AVG(tono), 2) AS tono_promedio
FROM (
  SELECT LOWER(REGEXP_EXTRACT(o, r'^([^,]+)')) AS org,
         SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tono
  FROM `gdelt-bq.gdeltv2.gkg_partitioned`, UNNEST(SPLIT(V2Organizations, ';')) AS o
  WHERE _PARTITIONTIME = TIMESTAMP(@dia)
    AND REGEXP_CONTAINS(V2Organizations, @regex)
)
WHERE REGEXP_CONTAINS(org, @regex)
GROUP BY org ORDER BY menciones DESC
""",
    "events_actores": """
SELECT COALESCE(IF(REGEXP_CONTAINS(Actor1Name, @regex), Actor1Name, NULL),
                IF(REGEXP_CONTAINS(Actor2Name, @regex), Actor2Name, NULL)) AS actor,
       COUNT(*) AS eventos, ROUND(AVG(AvgTone), 2) AS tono_promedio
FROM `gdelt-bq.gdeltv2.events_partitioned`
WHERE _PARTITIONTIME = TIMESTAMP(@dia)
  AND (REGEXP_CONTAINS(Actor1Name, @regex) OR REGEXP_CONTAINS(Actor2Name, @regex))
GROUP BY actor ORDER BY eventos DESC
""",
}


def gib(n: int) -> str:
    return f"{n / 1024**3:,.2f} GiB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dia", default=time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400)))
    ap.add_argument("--solo-dry-run", action="store_true")
    args = ap.parse_args()

    proyecto = os.environ["GCP_PROJECT_ID"]
    cliente = bigquery.Client(project=proyecto)
    params = [bigquery.ScalarQueryParameter("dia", "STRING", args.dia),
              bigquery.ScalarQueryParameter("regex", "STRING", regex_orgs())]
    print(f"día de partición: {args.dia} | tope por query: {gib(TOPE_BYTES)}")

    resumen = {"dia": args.dia, "consultas": {}}
    for nombre, sql in CONSULTAS.items():
        print(f"\n=== {nombre} ===")
        dry = cliente.query(sql, job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=params))
        estimado = dry.total_bytes_processed
        print(f"dry run: {gib(estimado)} estimados")
        r = {"bytes_estimados": estimado}
        if estimado > TOPE_BYTES:
            print(f"NO SE EJECUTA: supera el tope de {gib(TOPE_BYTES)}")
            r["ejecutada"] = False
        elif args.solo_dry_run:
            r["ejecutada"] = False
        else:
            t0 = time.perf_counter()
            job = cliente.query(sql, job_config=bigquery.QueryJobConfig(
                query_parameters=params, maximum_bytes_billed=TOPE_BYTES))
            filas = [dict(f) for f in job.result()]
            r.update({"ejecutada": True, "bytes_procesados": job.total_bytes_processed,
                      "bytes_facturados": job.total_bytes_billed,
                      "segundos": round(time.perf_counter() - t0, 1), "filas": filas})
            print(f"procesados {gib(job.total_bytes_processed)} | facturados {gib(job.total_bytes_billed or 0)} "
                  f"| {r['segundos']} s")
            for f in filas:
                print("  ", f)
            print(f"  total: {sum(list(f.values())[1] for f in filas)}")
        resumen["consultas"][nombre] = r
    print("\n=== resumen JSON ===")
    print(json.dumps(resumen, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
