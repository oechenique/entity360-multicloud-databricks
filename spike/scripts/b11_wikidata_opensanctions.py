"""Spike B.11: Wikidata como puente SEC (CIK) <-> GLEIF (LEI), y OpenSanctions.

1. Wikidata SPARQL: para los 16 CIK argentinos de B.9, ¿qué ítem tienen y qué LEI (P1278)?
2. Wikidata SPARQL: empresas argentinas (P17 = Argentina) con LEI y/o CIK: tamaño de la
   verdad de referencia.
3. GLEIF local (golden copy de B.8, pyarrow en streaming): verificar cada LEI de Wikidata
   (existe, nombre legal, país, estado) y cuántos LEI argentinos de Wikidata están en el
   universo AR de GLEIF.
4. OpenSanctions (targets.simple.csv, streaming): total, entidades con país AR por schema,
   y cruces con el universo: por LEI en identifiers y por nombre normalizado.

Wikidata pide User-Agent identificable: se toma de WIKIDATA_USER_AGENT (no se versiona).
Licencias: Wikidata CC0; GLEIF CC0; OpenSanctions CC BY-NC 4.0 (uso no comercial).

Uso:
    $env:WIKIDATA_USER_AGENT = "entity360 (portfolio) <mail>"
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\b11_wikidata_opensanctions.py
"""

import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import requests

SPARQL = "https://query.wikidata.org/sparql"
RAIZ = Path(__file__).resolve().parents[1]
GLEIF_ZIP = next((RAIZ / "data" / "gleif").glob("*-lei2-golden-copy.csv.zip"), None)
OS_DIR = RAIZ / "data" / "opensanctions"
OS_INDEX = "https://data.opensanctions.org/datasets/latest/default/index.json"

# CIK de B.9 (company_tickers.json de la SEC).
CIKS = {"YPF": 904851, "GGAL": 1114700, "PAM": 1469395, "BMA": 1347426, "TEO": 932470,
        "TGS": 931427, "EDN": 1395213, "CEPU": 1717161, "SUPV": 1517399, "BBAR": 913059,
        "CRESY": 1034957, "IRS": 933267, "LOMA": 1711375, "VIST": 1762506, "MELI": 1099590,
        "GLOB": 1557860}

SUFIJOS = r"\b(S\.?\s?A\.?\s?U?\.?|SOCIEDAD ANONIMA( UNIPERSONAL)?|S\.?R\.?L\.?|SOCIEDAD DE RESPONSABILIDAD LIMITADA|S\.?A\.?I\.?C\.?(Y\s?F\.?)?|INC\.?|CORP\.?|LTD\.?|LLC)\b"


def normalizar(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().upper()
    s = re.sub(SUFIJOS, " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sparql(sesion: requests.Session, consulta: str) -> list[dict]:
    r = sesion.get(SPARQL, params={"query": consulta, "format": "json"}, timeout=120)
    r.raise_for_status()
    time.sleep(1)  # pautas de uso del endpoint: sin ráfagas
    return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]


def paso1_ciks(s) -> list[dict]:
    print("=== 1. Wikidata: ítem y LEI de los 16 CIK argentinos ===")
    # Wikidata guarda el CIK como texto; puede estar con o sin ceros a la izquierda.
    valores = " ".join(f'"{c:010d}" "{c}"' for c in CIKS.values())
    filas = sparql(s, f"""
SELECT ?item ?itemLabel ?cik ?lei WHERE {{
  VALUES ?cik {{ {valores} }}
  ?item wdt:P5531 ?cik .
  OPTIONAL {{ ?item wdt:P1278 ?lei . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
}}""")
    por_cik = {}
    for f in filas:
        por_cik.setdefault(int(f["cik"]), []).append(f)
    salida = []
    for ticker, cik in CIKS.items():
        items = por_cik.get(cik, [])
        leis = sorted({f["lei"] for f in items if "lei" in f})
        fila = {"ticker": ticker, "cik": cik,
                "wikidata": sorted({f["item"].rsplit("/", 1)[1] for f in items}),
                "etiqueta": items[0]["itemLabel"] if items else None, "lei_wikidata": leis}
        salida.append(fila)
        print(f"  {ticker:6} CIK {cik:>8} -> {fila['wikidata'] or 'sin ítem'} "
              f"{fila['etiqueta'] or ''} | LEI: {leis or 'ninguno'}")
    return salida


def paso1b_tickers(s) -> list[dict]:
    """Puente alternativo: ticker en NYSE/Nasdaq (P414 con calificador P249)."""
    print("\n=== 1b. Wikidata por ticker (P414 NYSE/Nasdaq + calificador P249) ===")
    filas = sparql(s, """
SELECT ?ticker ?item ?itemLabel ?lei ?cik WHERE {
  VALUES ?ticker { %s }
  ?item p:P414 ?st . ?st pq:P249 ?ticker ; ps:P414 ?bolsa .
  VALUES ?bolsa { wd:Q13677 wd:Q82059 }   # NYSE, Nasdaq
  OPTIONAL { ?item wdt:P1278 ?lei . }
  OPTIONAL { ?item wdt:P5531 ?cik . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,en". }
}""" % " ".join(f'"{t}"' for t in CIKS))
    salida = []
    for t in CIKS:
        fs = [f for f in filas if f["ticker"] == t]
        leis = sorted({f["lei"] for f in fs if "lei" in f})
        salida.append({"ticker": t, "wikidata": fs[0]["item"].rsplit("/", 1)[1] if fs else None,
                       "etiqueta": fs[0]["itemLabel"] if fs else None, "lei_wikidata": leis})
        print(f"  {t:6} -> " + (f"{salida[-1]['wikidata']} {salida[-1]['etiqueta']} | LEI: {leis or 'ninguno'}"
                                if fs else "sin ítem por ticker"))
    print(f"  tickers con ítem: {sum(1 for x in salida if x['wikidata'])}/{len(CIKS)}; "
          f"con LEI: {sum(1 for x in salida if x['lei_wikidata'])}/{len(CIKS)}")
    return salida


def paso2_argentinas(s) -> dict:
    print("\n=== 2. Wikidata: empresas con país Argentina (P17 = Q414) e identificadores ===")
    filas = sparql(s, """
SELECT ?item ?lei ?cik WHERE {
  ?item wdt:P17 wd:Q414 .
  { ?item wdt:P1278 ?lei . } UNION { ?item wdt:P5531 ?cik . }
  OPTIONAL { ?item wdt:P1278 ?lei . }
  OPTIONAL { ?item wdt:P5531 ?cik . }
}""")
    items_lei = {f["item"] for f in filas if "lei" in f}
    items_cik = {f["item"] for f in filas if "cik" in f}
    leis = {f["lei"] for f in filas if "lei" in f}
    r = {"items_con_lei": len(items_lei), "items_con_cik": len(items_cik),
         "items_con_ambos": len(items_lei & items_cik), "leis_distintos": len(leis)}
    print(json.dumps(r, indent=2))
    return {**r, "_leis": leis}


def paso3_gleif(leis_buscados: set[str]) -> tuple[dict, dict, set[str]]:
    import pyarrow.compute as pc
    import pyarrow.csv as pacsv

    print("\n=== 3. GLEIF local: verificación de LEI de Wikidata y universo AR ===")
    cols = ["LEI", "Entity.LegalName", "Entity.LegalAddress.Country", "Entity.LegalJurisdiction",
            "Entity.EntityStatus", "Registration.RegistrationStatus"]
    encontrados, nombres_ar, leis_ar = {}, {}, set()
    t0 = time.perf_counter()
    with zipfile.ZipFile(GLEIF_ZIP) as z, z.open(z.namelist()[0]) as crudo:
        lector = pacsv.open_csv(crudo, read_options=pacsv.ReadOptions(block_size=64 << 20),
                                convert_options=pacsv.ConvertOptions(
                                    include_columns=cols, column_types={c: "string" for c in cols}))
        for lote in lector:
            pais = pc.fill_null(pc.equal(lote.column("Entity.LegalAddress.Country"), "AR"), False)
            jur = lote.column("Entity.LegalJurisdiction")
            jur_ar = pc.fill_null(pc.or_(pc.equal(jur, "AR"), pc.starts_with(jur, "AR-")), False)
            buscado = pc.is_in(lote.column("LEI"), value_set=__import__("pyarrow").array(sorted(leis_buscados)))
            mascara = pc.or_(pc.or_(pais, jur_ar), pc.fill_null(buscado, False))
            for fila in lote.filter(mascara).to_pylist():
                if fila["Entity.LegalAddress.Country"] == "AR" or (fila["Entity.LegalJurisdiction"] or "").startswith("AR"):
                    leis_ar.add(fila["LEI"])
                    nombres_ar[normalizar(fila["Entity.LegalName"])] = fila["LEI"]
                if fila["LEI"] in leis_buscados:
                    encontrados[fila["LEI"]] = {
                        "nombre_legal": fila["Entity.LegalName"],
                        "pais": fila["Entity.LegalAddress.Country"],
                        "jurisdiccion": fila["Entity.LegalJurisdiction"],
                        "estado": fila["Entity.EntityStatus"],
                        "registro": fila["Registration.RegistrationStatus"],
                    }
    print(f"  pasada GLEIF: {time.perf_counter() - t0:,.1f} s; universo AR: {len(leis_ar)} LEI")
    return encontrados, nombres_ar, leis_ar


def paso4_opensanctions(leis_ar: set[str], nombres_ar: dict) -> dict:
    print("\n=== 4. OpenSanctions (default, targets.simple.csv) ===")
    meta = requests.get(OS_INDEX, timeout=60).json()
    rec = next(r for r in meta["resources"] if r["name"] == "targets.simple.csv")
    OS_DIR.mkdir(parents=True, exist_ok=True)
    destino = OS_DIR / f"{meta['version']}-targets.simple.csv"
    if not destino.exists():
        t0 = time.perf_counter()
        with requests.get(rec["url"], stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for b in r.iter_content(8 << 20):
                    f.write(b)
        print(f"  bajado {destino.name}: {destino.stat().st_size / 2**20:,.1f} MB en {time.perf_counter() - t0:,.1f} s")
    print(f"  versión {meta['version']}, entity_count {meta['entity_count']:,}")

    csv.field_size_limit(2**31 - 1)
    total, schemas_ar, cruce_lei, cruce_nombre = 0, Counter(), [], []
    t0 = time.perf_counter()
    with open(destino, encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            total += 1
            paises = set(fila["countries"].split(";")) if fila["countries"] else set()
            if "ar" not in paises:
                continue
            schemas_ar[fila["schema"]] += 1
            if fila["schema"] not in ("Company", "Organization", "LegalEntity", "PublicBody"):
                continue
            ids = set(re.findall(r"\b[0-9A-Z]{18}[0-9]{2}\b", fila["identifiers"] or ""))
            for lei in ids & leis_ar:
                cruce_lei.append((fila["id"], fila["name"], lei, fila["dataset"]))
            clave = normalizar(fila["name"])
            if clave and clave in nombres_ar:
                cruce_nombre.append((fila["id"], fila["name"], nombres_ar[clave], fila["dataset"]))
    seg = time.perf_counter() - t0
    r = {"version": meta["version"], "total_targets": total, "segundos": round(seg, 1),
         "ar_por_schema": dict(schemas_ar.most_common()),
         "cruce_por_lei": len(cruce_lei), "cruce_por_nombre_normalizado": len(cruce_nombre)}
    print(json.dumps(r, indent=2, ensure_ascii=False))
    for x in cruce_lei[:10]:
        print("  LEI   ", x)
    for x in cruce_nombre[:15]:
        print("  nombre", x)
    return r


def main() -> int:
    ua = os.environ.get("WIKIDATA_USER_AGENT")
    if not ua or "@" not in ua:
        print("Falta WIKIDATA_USER_AGENT con contacto (pautas de uso de Wikidata).")
        return 2
    if not GLEIF_ZIP:
        print("Falta el golden copy de GLEIF en spike/data/gleif (correr b8 primero).")
        return 2
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept": "application/sparql-results+json"})

    ciks = paso1_ciks(s)
    por_ticker = paso1b_tickers(s)
    arg = paso2_argentinas(s)
    leis_wd_ciks = {l for c in ciks + por_ticker for l in c["lei_wikidata"]}
    encontrados, nombres_ar, leis_ar = paso3_gleif(leis_wd_ciks | arg["_leis"])

    print("\n  --- CIK -> LEI (Wikidata) -> GLEIF ---")
    con_lei = 0
    for c in ciks:
        for lei in c["lei_wikidata"]:
            con_lei += 1
            g = encontrados.get(lei)
            print(f"  {c['ticker']:6} {lei} -> " + (f"{g['nombre_legal']} | {g['pais']}/{g['jurisdiccion']} | "
                                                    f"{g['estado']} / {g['registro']}" if g else "NO está en GLEIF"))
    ciks_con_lei = sum(1 for c in ciks if c["lei_wikidata"])
    en_gleif = sum(1 for c in ciks if any(l in encontrados for l in c["lei_wikidata"]))
    arg_en_ar = len(arg["_leis"] & leis_ar)
    resumen = {
        "ciks_ar": len(ciks),
        "ciks_con_item_wikidata": sum(1 for c in ciks if c["wikidata"]),
        "ciks_con_lei_en_wikidata": ciks_con_lei,
        "ciks_con_lei_verificado_en_gleif": en_gleif,
        "wikidata_ar_items_con_lei": arg["items_con_lei"],
        "wikidata_ar_leis_en_universo_gleif_ar": arg_en_ar,
        "universo_gleif_ar": len(leis_ar),
        "cobertura_referencia_sobre_universo": f"{arg_en_ar / len(leis_ar):.1%}",
    }
    print("\n" + json.dumps(resumen, indent=2, ensure_ascii=False))

    os_res = paso4_opensanctions(leis_ar, nombres_ar)
    print("\n=== resumen JSON ===")
    print(json.dumps({"ciks": ciks, "resumen": resumen, "opensanctions": os_res}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
