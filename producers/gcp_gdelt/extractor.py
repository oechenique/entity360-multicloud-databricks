"""Productor GDELT (regla 06, ADR 0003): BigQuery sandbox -> respaldo en BigQuery -> UC Volume.

Cada corrida (una por hora, GitHub Actions):
1. Consulta GKG (V2Organizations) de las últimas VENTANA_HORAS con filtro de partición obligatorio,
   dry run antes (corta si estima más de TOPE_DRY_RUN) y maximum_bytes_billed = 1 GiB (D12).
   Match por el diccionario alias.json (frase completa, límites de palabra, exclusiones). Excluye los
   GKGRECORDID que ya están en el respaldo: idempotencia por identificador de GDELT.
2. Respaldo: load job (el sandbox no admite DML ni streaming) a entity360_gdelt.menciones,
   particionada por lote_utc. Las particiones vencen a los 60 días (sandbox).
3. Push: lo que hay en el respaldo posterior al lote_hasta del último manifest de `gdelt` en el
   volume. Así un push fallido se reintenta solo en la corrida siguiente (extracción y entrega
   separadas, como en la fase 3). Sin pendientes, no empuja nada (D6, capa 1).

La ventana es de 24 horas: el cron de Actions se atrasa o saltea corridas (el 2026-09-27 hubo huecos de
4,8 y 6,8 horas entre corridas). Con la exclusión por GKGRECORDID, releer lo ya visto no duplica nada;
cuesta ~100 MiB por corrida (la partición de ayer y la de hoy), ~75 GiB por mes contra 1 TiB gratis.

Variables de entorno:
    GOOGLE_CLOUD_PROJECT, GOOGLE_APPLICATION_CREDENTIALS   (WIF en Actions; ADC del usuario en local)
    DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET   (SP entity360-producer-gdelt)

Uso:
    python extractor.py [--ventana-horas 24] [--solo-leer]
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

import landing

VERSION = "gdelt-1.0"
FUENTE = "gdelt"
TABLA = "entity360_gdelt.menciones"
TOPE_DRY_RUN = 512 * 1024**2      # lo esperado es 50-150 MiB; más que esto es que algo cambió
TOPE_FACTURADO = 1024**3          # D12
ALIAS = Path(__file__).resolve().parent / "alias.json"

ESQUEMA = [
    bigquery.SchemaField("gkg_record_id", "STRING", "REQUIRED"),
    bigquery.SchemaField("fecha_gdelt", "TIMESTAMP"),
    bigquery.SchemaField("medio", "STRING"),
    bigquery.SchemaField("url", "STRING"),
    bigquery.SchemaField("entidad", "STRING", "REQUIRED"),
    bigquery.SchemaField("formas", "STRING", "REPEATED"),
    bigquery.SchemaField("tono", "FLOAT"),
    bigquery.SchemaField("lote_utc", "TIMESTAMP", "REQUIRED"),
]

SQL = """
WITH orgs AS (
  SELECT g.GKGRECORDID, g.DATE, g.SourceCommonName, g.DocumentIdentifier, g.V2Tone,
         LOWER(TRIM(REGEXP_EXTRACT(o, r'^([^,]+)'))) AS org
  FROM `gdelt-bq.gdeltv2.gkg_partitioned` AS g, UNNEST(SPLIT(g.V2Organizations, ';')) AS o
  WHERE g._PARTITIONTIME >= TIMESTAMP_TRUNC(@desde, DAY)           -- filtro de partición obligatorio
    AND g.DATE >= CAST(FORMAT_TIMESTAMP('%Y%m%d%H%M%S', @desde) AS INT64)
    AND REGEXP_CONTAINS(LOWER(g.V2Organizations), @regex_any)
)
SELECT GKGRECORDID AS gkg_record_id,
       PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING)) AS fecha_gdelt,
       SourceCommonName AS medio, DocumentIdentifier AS url, a.clave AS entidad,
       ARRAY_AGG(DISTINCT org ORDER BY org) AS formas,
       SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tono
FROM orgs, UNNEST(@alias) AS a
WHERE {match}
  {filtro_respaldo}
GROUP BY gkg_record_id, fecha_gdelt, medio, url, entidad, tono
"""

# Una forma de organización (org, en minúsculas) es de la entidad `a` si contiene uno de sus alias
# y ninguna de sus exclusiones. Los tests la corren tal cual en BigQuery (tests/gcp_gdelt).
MATCH = "REGEXP_CONTAINS(org, a.regex) AND (a.excluir = '' OR NOT REGEXP_CONTAINS(org, a.excluir))"

FILTRO_RESPALDO = ("AND GKGRECORDID NOT IN (SELECT gkg_record_id FROM `{tabla}` "
                   "WHERE lote_utc >= TIMESTAMP_SUB(@desde, INTERVAL 1 DAY))")


def frase(forma: str) -> str:
    return r"\b" + r"\s+".join(forma.split()) + r"\b"


def reglas() -> tuple[list[tuple[str, str, str]], str]:
    """(clave, regex, excluir) por entidad, y la unión de todos los alias (prefiltro)."""
    ents = json.loads(ALIAS.read_text(encoding="utf-8"))["entidades"]
    filas, todas = [], []
    for e in ents:
        formas = [frase(a["forma"]) for a in e["alias"]]
        todas += formas
        excluir = "(" + "|".join(frase(x) for x in e["excluir"]) + ")" if e.get("excluir") else ""
        filas.append((e["clave"], "(" + "|".join(formas) + ")", excluir))
    return filas, "(" + "|".join(todas) + ")"


def patrones() -> tuple[list, str]:
    """reglas() como parámetros de la consulta: un STRUCT(clave, regex, excluir) por entidad."""
    filas, regex_any = reglas()
    return [bigquery.StructQueryParameter(
        None,
        bigquery.ScalarQueryParameter("clave", "STRING", clave),
        bigquery.ScalarQueryParameter("regex", "STRING", regex),
        bigquery.ScalarQueryParameter("excluir", "STRING", excluir)) for clave, regex, excluir in filas], regex_any


def iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def extraer(c: bigquery.Client, tabla: str, desde: datetime, hay_respaldo: bool) -> tuple[list[dict], dict]:
    alias, regex_any = patrones()
    sql = SQL.format(match=MATCH, filtro_respaldo=FILTRO_RESPALDO.format(tabla=tabla) if hay_respaldo else "")
    params = [bigquery.ScalarQueryParameter("desde", "TIMESTAMP", desde),
              bigquery.ScalarQueryParameter("regex_any", "STRING", regex_any),
              bigquery.ArrayQueryParameter("alias", "STRUCT", alias)]
    est = c.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                                          query_parameters=params)).total_bytes_processed
    if est > TOPE_DRY_RUN:
        raise RuntimeError(f"dry run estima {est / 2**20:,.0f} MiB (> {TOPE_DRY_RUN / 2**20:,.0f}): no se ejecuta")
    job = c.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params,
                                                          maximum_bytes_billed=TOPE_FACTURADO))
    filas = [dict(f) for f in job.result()]
    return filas, {"dry_run_mib": round(est / 2**20, 1),
                   "facturados_mib": round((job.total_bytes_billed or 0) / 2**20, 1)}


def respaldar(c: bigquery.Client, tabla: str, filas: list[dict], lote: datetime) -> None:
    datos = [{**{k: iso(v) for k, v in f.items()}, "lote_utc": lote.isoformat()} for f in filas]
    cfg = bigquery.LoadJobConfig(schema=ESQUEMA, write_disposition="WRITE_APPEND",
                                 create_disposition="CREATE_IF_NEEDED",
                                 time_partitioning=bigquery.TimePartitioning(type_="DAY", field="lote_utc"))
    c.load_table_from_json(datos, tabla, job_config=cfg).result()


def pendientes(c: bigquery.Client, tabla: str, hasta: str | None) -> list[dict]:
    """Filas del respaldo posteriores al último lote entregado al volume."""
    sql = f"SELECT * FROM `{tabla}`" + (" WHERE lote_utc > @hasta" if hasta else "")
    params = [bigquery.ScalarQueryParameter("hasta", "TIMESTAMP", hasta)] if hasta else []
    job = c.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params,
                                                          maximum_bytes_billed=TOPE_FACTURADO))
    filas = [{k: iso(v) for k, v in dict(f).items()} for f in job.result()]
    return sorted(filas, key=lambda f: (f["lote_utc"], f["gkg_record_id"], f["entidad"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ventana-horas", type=int, default=24)
    ap.add_argument("--solo-leer", action="store_true", help="consulta y resume: no respalda ni empuja")
    a = ap.parse_args()
    t0 = time.perf_counter()
    proyecto = os.environ["GOOGLE_CLOUD_PROJECT"]
    tabla = f"{proyecto}.{TABLA}"
    c = bigquery.Client(project=proyecto, location="US")
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    desde = ahora - timedelta(hours=a.ventana_horas)

    try:
        c.get_table(tabla)
        hay_respaldo = True
    except NotFound:
        hay_respaldo = False
    nuevas, costo = extraer(c, tabla, desde, hay_respaldo)
    por_entidad = {}
    for f in nuevas:
        por_entidad[f["entidad"]] = por_entidad.get(f["entidad"], 0) + 1
    print(f"consulta desde {desde:%Y-%m-%d %H:%M} UTC: dry run {costo['dry_run_mib']} MiB, "
          f"facturados {costo['facturados_mib']} MiB | {len(nuevas)} menciones nuevas {por_entidad}")
    if a.solo_leer:
        return 0

    if nuevas:
        respaldar(c, tabla, nuevas, ahora)
        print(f"respaldo: {len(nuevas)} filas (load job, lote {ahora:%Y-%m-%dT%H:%M:%SZ})")
        hay_respaldo = True

    vol = landing.Volume()
    anterior = vol.ultimo_manifest(FUENTE)
    hasta = anterior.get("lote_hasta") if anterior else None
    filas = pendientes(c, tabla, hasta) if hay_respaldo else []
    if not filas:
        latido = landing.latido(vol, FUENTE, VERSION, anterior) if anterior else "sin latido (no hay manifest previo)"
        print(f"push: sin pendientes (último lote entregado: {hasta or '-'}); {latido} "
              f"({time.perf_counter() - t0:,.1f} s)")
        return 0
    extra = {"lote_desde": filas[0]["lote_utc"], "lote_hasta": filas[-1]["lote_utc"],
             "ventana_horas": a.ventana_horas, "consulta": costo,
             "licencia": "GDELT: uso libre y sin restricciones, con cita y enlace",
             "atribucion": "Datos: The GDELT Project (https://www.gdeltproject.org/)"}
    r = landing.publicar(vol, FUENTE, VERSION, filas, extra)
    print(f"push: {r} ({time.perf_counter() - t0:,.1f} s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Principio 9: ni el proyecto ni el host del workspace van a los logs.
        detalle = traceback.format_exc()
        for secreto in (os.environ.get("GOOGLE_CLOUD_PROJECT"), urlparse(os.environ.get("DATABRICKS_HOST", "")).netloc):
            if secreto:
                detalle = detalle.replace(secreto, "<OCULTO>")
        print(detalle, file=sys.stderr)
        sys.exit(1)
