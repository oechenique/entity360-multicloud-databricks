"""Match de alias de GDELT (regla 06): frase completa entre límites de palabra, con exclusiones.

Los casos son formas reales de V2Organizations de la muestra del diagnóstico
(producers/gcp_gdelt/evidencia/alias-2026-09-19_25.txt) y del spike (B.10: "nombres cortos traen
mucho ruido: Galicia España, Macron"). Se verifican dos veces:
- con `re` de Python (re.ASCII: \\b de RE2 es ASCII), sin nube;
- en BigQuery, con la misma condición MATCH de la consulta del extractor. No lee ninguna tabla
  (0 bytes procesados); se saltea sin ADC.
"""

import json
import re

import pytest

import extractor

CASOS = [
    # Banco Galicia: la forma traducida palabra por palabra, también dentro de frases más largas
    ("bank galicia", {"BANCO_GALICIA"}),
    ("branch bank galicia", {"BANCO_GALICIA"}),
    ("a branch bank galicia", {"BANCO_GALICIA"}),
    ("bank galicia to hills viewpoint", {"BANCO_GALICIA"}),
    # Grupo Financiero Galicia es GGAL, no el banco
    ("group financial galicia", {"GGAL"}),
    # "galicia" sola y la región de España: nada
    ("galicia", set()),
    ("parliament of galicia", set()),
    ("group galicia", set()),
    ("school galician", set()),
    ("bank galician", set()),            # descartado: ambiguo con bancos gallegos
    # Banco Macro sí; "macro" sola, Macron y la macroeconomía no
    ("banco macro", {"BMA"}),
    ("macro", set()),
    ("macron", set()),
    ("emmanuel macron", set()),
    ("macron government", set()),
    ("division macro", set()),
    ("roubini macro associates", set()),
    ("institution for macroeconomics", set()),
    ("world bank macro poverty outlook", set()),   # contiene "bank macro": lo saca la exclusión
    # Otros nombres cortos o frases comunes
    ("bank french", set()),              # BNP Paribas / Société Générale, no BBVA Argentina
    ("federation soccer buenos pampas", set()),
    ("free market institute", set()),    # "mercado libre" traducido, no MercadoLibre
    ("mercadolibre", {"MELI"}),
]


def org(entrada: str) -> str:
    """Como la consulta: LOWER(TRIM(REGEXP_EXTRACT(o, r'^([^,]+)'))) de cada 'nombre,offset'."""
    return re.match(r"^([^,]+)", entrada).group(1).strip().lower()


def entidades(forma: str) -> set[str]:
    filas, _ = extractor.reglas()
    return {clave for clave, regex, excluir in filas
            if re.search(regex, forma, re.ASCII) and not (excluir and re.search(excluir, forma, re.ASCII))}


@pytest.mark.parametrize("forma,esperado", CASOS)
def test_match(forma, esperado):
    assert entidades(forma) == esperado


@pytest.mark.parametrize("forma,esperado", [c for c in CASOS if c[1]])
def test_prefiltro_no_pierde_matches(forma, esperado):
    """El prefiltro (regex_any sobre V2Organizations) deja pasar todo lo que después matchea."""
    _, regex_any = extractor.reglas()
    assert re.search(regex_any, f"otra cosa,12;{forma.upper()},345".lower(), re.ASCII)


def test_org_de_v2organizations():
    assert [org(o) for o in "Bank Galicia,1024;Parliament Of Galicia,77".split(";")] == \
        ["bank galicia", "parliament of galicia"]


def test_diccionario():
    """Formas en minúsculas, solo letras/dígitos/espacios (frase() no escapa), nunca nombres cortos
    ambiguos, y cada alias resuelve a su propia entidad y a ninguna otra."""
    ents = json.loads(extractor.ALIAS.read_text(encoding="utf-8"))["entidades"]
    prohibidos = {"galicia", "macro", "pampa", "irsa", "free market"}
    for e in ents:
        for a in e["alias"]:
            assert re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", a["forma"]), a["forma"]
            assert a["forma"] not in prohibidos
            assert entidades(a["forma"]) == {e["clave"]}, a["forma"]


def test_match_en_bigquery(bq):
    from google.cloud import bigquery
    alias, _ = extractor.patrones()
    sql = (f"SELECT org, a.clave FROM UNNEST(@orgs) AS org, UNNEST(@alias) AS a "
           f"WHERE {extractor.MATCH}")
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("orgs", "STRING", [f for f, _ in CASOS]),
        bigquery.ArrayQueryParameter("alias", "STRUCT", alias)],
        maximum_bytes_billed=extractor.TOPE_FACTURADO)
    job = bq.query(sql, job_config=cfg)
    obtenido = {f: set() for f, _ in CASOS}
    for fila in job.result():
        obtenido[fila["org"]].add(fila["clave"])
    assert obtenido == dict(CASOS)
    assert (job.total_bytes_processed or 0) == 0
