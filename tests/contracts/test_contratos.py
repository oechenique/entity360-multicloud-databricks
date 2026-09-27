"""Contratos de llegada (regla 09): contracts/verificar.py con Soda Core y DuckDB, sin red.

Correr con el entorno de los contratos:
    contracts\\.venv\\Scripts\\python.exe -m pytest tests\\contracts

Los lotes de tests/contracts/datos son muestras reales de lotes aterrizados (2026-09-25 a 27); a
SEC EDGAR se le sacó `filings` (el historial de presentaciones, que el contrato no mira) para que
el archivo sea chico. Los casos que tienen que ir a cuarentena son copias de esas muestras con un
solo campo roto, que es justo lo que cada test describe.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "contracts"))
import alertas  # noqa: E402
import verificar  # noqa: E402

DATOS = Path(__file__).resolve().parent / "datos"
EXTRAIDO = json.loads((DATOS / "extraido_utc.json").read_text(encoding="utf-8"))


def lote(fuente: str, lineas: list[str] | None = None) -> tuple[bytes, dict]:
    """Contenido del lote y un manifest coherente con él (como el que escribe el productor)."""
    if lineas is None:
        contenido = (DATOS / f"{fuente}.jsonl").read_bytes()
    else:
        contenido = ("\n".join(lineas) + "\n").encode()
    n = sum(1 for l in contenido.decode().split("\n") if l.strip())
    return contenido, {"fuente": fuente, "archivo": f"{fuente}_T.jsonl", "registros": n,
                       "sha256": hashlib.sha256(contenido).hexdigest(), "extraido_utc": EXTRAIDO[fuente]}


def registros(fuente: str) -> list[dict]:
    return [json.loads(l) for l in (DATOS / f"{fuente}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def con_cambio(fuente: str, cambiar) -> tuple[bytes, dict]:
    rs = registros(fuente)
    cambiar(rs)
    return lote(fuente, [json.dumps(r, ensure_ascii=False) for r in rs])


# ------------------------------------------------------------------ lotes reales

@pytest.mark.parametrize("fuente", ["sqlserver_cdc", "sec_edgar", "gdelt", "wikidata"])
def test_lotes_reales_aprobados_sin_avisos(fuente):
    v = verificar.verificar(fuente, *lote(fuente))
    assert v["estado"] == "aprobado", v["fallas_criticas"]
    assert v["advertencias"] == []


def test_volumen_fuera_de_rango_es_aviso_no_cuarentena():
    """La muestra de OpenSanctions tiene 50 entidades (el export filtrado trae ~2.600)."""
    v = verificar.verificar("opensanctions", *lote("opensanctions"))
    assert v["estado"] == "aprobado"
    assert v["advertencias"] == ["row_count volumen"]


# ------------------------------------------------------------------ integridad contra el manifest

def test_sha256_distinto_del_manifest():
    contenido, m = lote("wikidata")
    m["sha256"] = "0" * 64
    v = verificar.verificar("wikidata", contenido, m)
    assert v["estado"] == "cuarentena" and v["fallas_criticas"] == ["sha256 del manifest"]


def test_registros_distintos_del_manifest():
    contenido, m = lote("wikidata")
    m["registros"] += 1
    v = verificar.verificar("wikidata", contenido, m)
    assert v["fallas_criticas"] == ["registros del manifest"]


# ------------------------------------------------------------------ checks críticos por fuente

def test_cdc_operacion_desconocida():
    def f(rs):
        rs[0]["op"] = "upsert"
    v = verificar.verificar("sqlserver_cdc", *con_cambio("sqlserver_cdc", f))
    assert v["estado"] == "cuarentena" and v["fallas_criticas"] == ["invalid op"]


def test_cdc_lsn_mal_formado():
    def f(rs):
        rs[0]["lsn"] = "2E000028E00005"
    assert verificar.verificar("sqlserver_cdc", *con_cambio("sqlserver_cdc", f))["fallas_criticas"] == ["invalid lsn"]


def test_sec_cambio_de_formato_falla_la_proyeccion():
    def f(rs):
        for r in rs:
            r["submissions"]["entityName"] = r["submissions"].pop("name")
    v = verificar.verificar("sec_edgar", *con_cambio("sec_edgar", f))
    assert v["estado"] == "cuarentena"
    assert v["fallas_criticas"] == ["proyección del formato de la fuente"]


def test_sec_cik_repetido():
    def f(rs):
        rs[1]["cik"] = rs[0]["cik"]
    assert verificar.verificar("sec_edgar", *con_cambio("sec_edgar", f))["fallas_criticas"] == ["duplicate"]


def test_gdelt_entidad_fuera_del_diccionario():
    def f(rs):
        rs[0]["entidad"] = "GALICIA"
    assert verificar.verificar("gdelt", *con_cambio("gdelt", f))["fallas_criticas"] == ["invalid entidad"]


def test_gdelt_columna_faltante_falla_el_esquema():
    def f(rs):
        for r in rs:
            del r["tono"]
    assert "schema" in verificar.verificar("gdelt", *con_cambio("gdelt", f))["fallas_criticas"]


def test_wikidata_sin_etiquetas():
    def f(rs):
        rs[0]["etiqueta_es"] = rs[0]["etiqueta_en"] = None
    v = verificar.verificar("wikidata", *con_cambio("wikidata", f))
    assert v["fallas_criticas"] == ["failed_rows con alguna etiqueta"]


# ------------------------------------------------------------------ avisos

def test_gdelt_menciones_viejas_son_aviso():
    """La frescura se mide contra el extraido_utc del manifest: un lote con menciones de 3 días antes."""
    contenido, m = lote("gdelt")
    m["extraido_utc"] = "2026-09-30T20:15:04+00:00"
    v = verificar.verificar("gdelt", contenido, m)
    assert v["estado"] == "aprobado" and v["advertencias"] == ["freshness"]


def test_veredicto_reproducible_verificado_tarde():
    """Mismo lote y manifest: mismo veredicto aunque se verifique días después."""
    a = verificar.verificar("gdelt", *lote("gdelt"))
    b = verificar.verificar("gdelt", *lote("gdelt"))
    assert [c for c in a["checks"]] == [c for c in b["checks"]]


# ------------------------------------------------------------------ piezas

def test_valores_validos_de_gdelt_son_las_claves_del_diccionario():
    alias = json.loads((RAIZ / "producers" / "gcp_gdelt" / "alias.json").read_text(encoding="utf-8"))
    claves = [e["clave"] for e in alias["entidades"]]
    yml = (RAIZ / "contracts" / "gdelt.yml").read_text(encoding="utf-8")
    assert f"valid_values: [{', '.join(claves)}]" in yml


def test_contrato_de():
    r = "/Volumes/entity360/landing/raw/gdelt/ingest_date=2026-09-27/gdelt_20260927T201512Z.jsonl"
    assert verificar.contrato_de(r).endswith("ingest_date=2026-09-27/_contrato_20260927T201512Z.json")


def test_alerta_sin_canal_no_frena(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert alertas.enviar("t", "x") is False
    assert "sin canal configurado" in capsys.readouterr().err
