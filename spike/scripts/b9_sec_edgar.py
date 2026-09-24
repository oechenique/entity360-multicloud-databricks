"""Spike B.9: SEC EDGAR, submissions JSON de empresas argentinas que presentan ante la SEC.

1. company_tickers.json: CIK real de un conjunto de tickers argentinos conocidos (ADRs).
2. submissions (data.sec.gov/submissions/CIK##########.json) de cada una: identidad,
   domicilio, nombres anteriores, formularios recientes, tamaño del JSON.
3. Qué campos sirven para cruzar con GLEIF (nombre, país, LEI si viene) → insumo de la
   resolución de identidades.

La SEC exige User-Agent con nombre y mail, y limita a 10 requests/s: se toma el User-Agent de
SEC_USER_AGENT (no se versiona) y se espera 0,2 s entre requests.

Uso:
    $env:SEC_USER_AGENT = "entity360 (portfolio) Nombre Apellido <mail>"
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\b9_sec_edgar.py
"""

import json
import os
import sys
import time
from collections import Counter

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
PAUSA = 0.2  # 5 req/s, la mitad del límite de la SEC

# ADRs/acciones de empresas argentinas en bolsas de EE. UU. (candidatas del universo).
CANDIDATOS = ["YPF", "GGAL", "PAM", "BMA", "TEO", "TGS", "EDN", "CEPU", "SUPV", "BBAR",
              "CRESY", "IRS", "LOMA", "VIST", "MELI", "GLOB", "DESP"]
DETALLE = ["YPF", "GGAL", "PAM"]  # los 2-3 que pide la regla 02


def main() -> int:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua or "@" not in ua:
        print("Falta SEC_USER_AGENT con nombre y mail (lo exige la SEC).")
        return 2
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})

    print("=== 1. CIK de tickers argentinos (company_tickers.json) ===")
    r = s.get(TICKERS_URL, timeout=60)
    r.raise_for_status()
    por_ticker = {v["ticker"]: v for v in r.json().values()}
    print(f"tickers en el archivo: {len(por_ticker):,}")
    encontrados = {}
    for t in CANDIDATOS:
        v = por_ticker.get(t)
        print(f"  {t:6} -> " + (f"CIK {v['cik_str']:>8}  {v['title']}" if v else "no está"))
        if v:
            encontrados[t] = v["cik_str"]
    time.sleep(PAUSA)

    print("\n=== 2. submissions de", ", ".join(DETALLE), "===")
    resumen = []
    for t in DETALLE:
        cik = encontrados[t]
        t0 = time.perf_counter()
        r = s.get(SUBMISSIONS_URL.format(cik=cik), timeout=60)
        r.raise_for_status()
        seg = time.perf_counter() - t0
        d = r.json()
        rec = d["filings"]["recent"]
        formularios = Counter(rec["form"])
        negocio = d.get("addresses", {}).get("business", {})
        fila = {
            "ticker": t,
            "cik": d["cik"],
            "nombre": d["name"],
            "entityType": d.get("entityType"),
            "sic": f"{d.get('sic')} {d.get('sicDescription')}",
            "stateOfIncorporation": d.get("stateOfIncorporation"),
            "stateOfIncorporationDescription": d.get("stateOfIncorporationDescription"),
            "domicilio_negocio": f"{negocio.get('city')}, {negocio.get('stateOrCountryDescription')}",
            "tickers": d.get("tickers"),
            "exchanges": d.get("exchanges"),
            "lei": d.get("lei"),
            "ein": d.get("ein"),
            "formerNames": [f["name"] for f in d.get("formerNames", [])],
            "presentaciones_recientes": len(rec["form"]),
            "ultima_presentacion": max(rec["filingDate"]) if rec["filingDate"] else None,
            "formularios_top": dict(formularios.most_common(5)),
            "archivos_historicos_extra": len(d["filings"].get("files", [])),
            "json_kb": round(len(r.content) / 1024, 1),
            "segundos": round(seg, 2),
        }
        resumen.append(fila)
        print(json.dumps(fila, indent=2, ensure_ascii=False))
        time.sleep(PAUSA)

    print("\n=== 3. claves de primer nivel del JSON de submissions ===")
    print(sorted(d.keys()))
    con_lei = sum(1 for f in resumen if f["lei"])
    print(f"\nempresas con LEI en el JSON de la SEC: {con_lei}/{len(resumen)}")
    print(f"candidatas argentinas con CIK: {len(encontrados)}/{len(CANDIDATOS)}")
    print("\n=== resumen JSON ===")
    print(json.dumps({"ciks": encontrados, "detalle": resumen}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
