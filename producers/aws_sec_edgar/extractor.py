"""Lambda de extracción (regla 05): SEC EDGAR submissions -> S3 propio.

Una vez por día (EventBridge Scheduler):
1. Baja data.sec.gov/submissions/CIK##########.json de cada emisor del universo, con el
   User-Agent que exige la SEC (nombre y mail, en SEC_USER_AGENT) y a <= 5 requests/s.
2. Idempotencia por CIK + fecha de la última presentación: compara con estado/ultimas.json en
   el bucket y se queda solo con los emisores que tienen una presentación nueva.
3. Si hay cambios, escribe el lote crudo (lotes/ingest_date=.../sec_edgar_<ts>.jsonl) y DESPUÉS
   su _manifest_<ts>.json (la creación del manifest dispara la Lambda de entrega). Al final
   actualiza estado/ultimas.json.
4. Sin cambios, no escribe nada (D6, capa 1).

Variables de entorno: BUCKET, SEC_USER_AGENT.
"""

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import boto3

VERSION = "sec-edgar-extractor-1.0"
FUENTE = "sec_edgar"
URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
PAUSA = 0.2
ESTADO = "estado/ultimas.json"

s3 = boto3.client("s3")


def bajar(cik: int, ua: str) -> dict:
    req = urllib.request.Request(URL.format(cik=cik), headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    cuerpo = gzip.decompress(cuerpo)
                return json.loads(cuerpo)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and intento < 2:  # límite de la SEC: esperar y reintentar
                time.sleep(2 ** (intento + 1))
                continue
            raise


def ultima_presentacion(d: dict) -> dict:
    rec = d["filings"]["recent"]
    if not rec["accessionNumber"]:
        return {"fecha": None, "accession": None}
    # recent viene ordenado de la más nueva a la más vieja
    return {"fecha": rec["filingDate"][0], "accession": rec["accessionNumber"][0], "form": rec["form"][0]}


def leer_estado(bucket: str) -> dict:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=ESTADO)["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {}


def lambda_handler(event, context):
    bucket, ua = os.environ["BUCKET"], os.environ["SEC_USER_AGENT"]
    universo = json.loads((Path(__file__).parent / "universo.json").read_text(encoding="utf-8"))["emisores"]
    estado = leer_estado(bucket)
    ahora = datetime.now(timezone.utc)

    lineas, nuevo_estado, sin_cambios = [], dict(estado), 0
    for e in universo:
        d = bajar(e["cik"], ua)
        ultima = ultima_presentacion(d)
        clave = str(e["cik"])
        if estado.get(clave, {}).get("accession") == ultima["accession"]:
            sin_cambios += 1
        else:
            lineas.append(json.dumps({"cik": e["cik"], "ticker": e["ticker"], "ultima_presentacion": ultima,
                                      "extraido_utc": ahora.isoformat(), "submissions": d}, ensure_ascii=False))
            nuevo_estado[clave] = ultima
        time.sleep(PAUSA)

    resumen = {"emisores": len(universo), "con_presentacion_nueva": len(lineas), "sin_cambios": sin_cambios}
    if not lineas:
        print(json.dumps({**resumen, "resultado": "sin cambios: no se escribe lote"}))
        return resumen

    ts = ahora.strftime("%Y%m%dT%H%M%SZ")
    carpeta = f"lotes/ingest_date={ahora:%Y-%m-%d}"
    datos = ("\n".join(lineas)).encode("utf-8")
    clave_datos = f"{carpeta}/{FUENTE}_{ts}.jsonl"
    manifest = {
        "fuente": FUENTE, "archivo": clave_datos.rsplit("/", 1)[1], "registros": len(lineas),
        "sha256": hashlib.sha256(datos).hexdigest(), "extraido_utc": ahora.isoformat(),
        "producer_version": VERSION, "ciks": [json.loads(l)["cik"] for l in lineas],
    }
    s3.put_object(Bucket=bucket, Key=clave_datos, Body=datos, ContentType="application/x-ndjson")
    s3.put_object(Bucket=bucket, Key=f"{carpeta}/_manifest_{ts}.json",
                  Body=json.dumps(manifest, indent=2).encode("utf-8"), ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=ESTADO, Body=json.dumps(nuevo_estado, indent=2).encode("utf-8"),
                  ContentType="application/json")
    print(json.dumps({**resumen, "lote": clave_datos, "bytes": len(datos), "sha256": manifest["sha256"]}))
    return {**resumen, "lote": clave_datos}
