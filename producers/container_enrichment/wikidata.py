"""Wikidata: empresas del universo con sus identificadores (LEI, CIK, ticker, sitio web, país).

Consultas validadas en el spike (B.11):
1. Ítems con país Argentina (P17 = Q414) que tienen LEI (P1278) o CIK (P5531).
2. Ítems de los emisores AR ante la SEC por CIK (con y sin ceros a la izquierda).
3. Los mismos emisores por ticker en NYSE/Nasdaq (P414 con calificador P249).
Después, una consulta de detalle por ítem. Una fila por ítem, con el motivo por el que entró.

Wikidata es una **señal extra** del matching, no la verdad de referencia (D11).
Pautas del endpoint: User-Agent con contacto, consultas en serie con pausa, y respetar Retry-After.
Licencia de los datos: CC0 1.0.
"""

import time

import requests

SPARQL = "https://query.wikidata.org/sparql"
BOLSAS = {"Q13677": "NYSE", "Q82059": "NASDAQ"}
ATRIBUCION = {"licencia": "CC0 1.0", "atribucion": "Datos: Wikidata (wikidata.org), CC0"}


def consultar(s: requests.Session, q: str) -> list[dict]:
    for intento in range(4):
        r = s.get(SPARQL, params={"query": q, "format": "json"}, timeout=120)
        if r.status_code in (429, 503) and intento < 3:
            time.sleep(int(r.headers.get("Retry-After", 10 * (intento + 1))))
            continue
        r.raise_for_status()
        time.sleep(1)  # sin ráfagas
        return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[1]


def extraer(ua: str, emisores: list[dict]) -> tuple[list[dict], dict]:
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept": "application/sparql-results+json"})
    motivos: dict[str, set[str]] = {}

    def sumar(filas, motivo):
        for f in filas:
            motivos.setdefault(qid(f["item"]), set()).add(motivo)

    sumar(consultar(s, """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P17 wd:Q414 .
  { ?item wdt:P1278 [] . } UNION { ?item wdt:P5531 [] . }
}"""), "pais_ar_con_lei_o_cik")
    ciks = " ".join(f'"{e["cik"]:010d}" "{e["cik"]}"' for e in emisores)
    sumar(consultar(s, f"SELECT DISTINCT ?item WHERE {{ VALUES ?cik {{ {ciks} }} ?item wdt:P5531 ?cik . }}"),
          "cik_emisor_sec")
    tickers = " ".join(f'"{e["ticker"]}"' for e in emisores)
    sumar(consultar(s, f"""
SELECT DISTINCT ?item WHERE {{
  VALUES ?ticker {{ {tickers} }}
  VALUES ?bolsa {{ {" ".join("wd:" + b for b in BOLSAS)} }}
  ?item p:P414 ?st . ?st pq:P249 ?ticker ; ps:P414 ?bolsa .
}}"""), "ticker_emisor_sec")

    items = " ".join(f"wd:{q}" for q in sorted(motivos))
    detalle = consultar(s, f"""
SELECT ?item ?es ?en ?lei ?cik ?bolsa ?ticker ?web ?pais WHERE {{
  VALUES ?item {{ {items} }}
  OPTIONAL {{ ?item rdfs:label ?es . FILTER(LANG(?es) = "es") }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P1278 ?lei . }}
  OPTIONAL {{ ?item wdt:P5531 ?cik . }}
  OPTIONAL {{ ?item p:P414 ?st . ?st ps:P414 ?bolsa ; pq:P249 ?ticker . }}
  OPTIONAL {{ ?item wdt:P856 ?web . }}
  OPTIONAL {{ ?item wdt:P17 ?p . ?p wdt:P297 ?pais . }}
}}""")
    filas = {q: {"qid": q, "etiqueta_es": None, "etiqueta_en": None, "leis": set(), "ciks": set(),
                 "tickers": set(), "sitios_web": set(), "paises": set(), "motivos": sorted(m)}
             for q, m in motivos.items()}
    for d in detalle:
        f = filas[qid(d["item"])]
        f["etiqueta_es"] = f["etiqueta_es"] or d.get("es")
        f["etiqueta_en"] = f["etiqueta_en"] or d.get("en")
        for campo, clave in (("leis", "lei"), ("sitios_web", "web"), ("paises", "pais")):
            if d.get(clave):
                f[campo].add(d[clave])
        if d.get("cik"):
            f["ciks"].add(int(d["cik"]))  # Wikidata lo guarda como texto, con o sin ceros
        if d.get("ticker"):
            f["tickers"].add(f"{BOLSAS.get(qid(d['bolsa']), qid(d['bolsa']))}:{d['ticker']}")
    salida = [{k: sorted(v) if isinstance(v, set) else v for k, v in f.items()}
              for _, f in sorted(filas.items())]
    return salida, {"consultas": 4, **ATRIBUCION}
