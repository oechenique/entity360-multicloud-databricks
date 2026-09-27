"""Capa 2 de idempotencia de Bronze (D6)."""

import pytest

import capa2

R = "/Volumes/entity360/landing/raw/wikidata/ingest_date=2026-09-26"


def arch(ts, sha, lineas=20):
    return {"ruta": f"{R}/wikidata_{ts}.jsonl", "sha256": sha, "lineas": lineas}


def man(sha, registros=20):
    return {"sha256": sha, "registros": registros}


def test_manifest_de():
    assert capa2.manifest_de(f"{R}/wikidata_20260926T222617Z.jsonl") == f"{R}/_manifest_20260926T222617Z.json"
    assert capa2.manifest_de("/x/sqlserver_cdc/d=1/sqlserver_cdc_20260925T215645Z.jsonl").endswith("/_manifest_20260925T215645Z.json")


def test_lote_nuevo():
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {})
    assert r["estado"] == "ingerido_bronze"


def test_sin_manifest_falla_el_lote_entero():
    a, b = arch("T1", "s1"), arch("T2", "s2")
    with pytest.raises(capa2.ManifestPendiente, match="T2"):
        capa2.clasificar([a, b], {a["ruta"]: man("s1"), b["ruta"]: None}, {})


def test_reenvio_identico_con_otro_nombre_es_duplicado():
    viejo, nuevo = arch("T1", "s1"), arch("T2", "s1")
    [r] = capa2.clasificar([nuevo], {nuevo["ruta"]: man("s1")}, {"s1": viejo["ruta"]})
    assert r["estado"] == "duplicado" and "wikidata_T1.jsonl" in r["motivo"]


def test_mismo_archivo_reprocesado_no_es_duplicado():
    """Checkpoint borrado: el mismo archivo vuelve a entrar; el MERGE por (sha256, linea) no duplica."""
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {"s1": a["ruta"]})
    assert r["estado"] == "ingerido_bronze"


def test_duplicado_dentro_del_mismo_lote():
    a, b = arch("T1", "s1"), arch("T2", "s1")
    r = capa2.clasificar([b, a], {a["ruta"]: man("s1"), b["ruta"]: man("s1")}, {})
    assert [x["estado"] for x in r] == ["ingerido_bronze", "duplicado"]


@pytest.mark.parametrize("m,motivo", [(man("otro"), "sha256"), (man("s1", registros=19), "19")])
def test_errores(m, motivo):
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: m}, {})
    assert r["estado"] == "error" and motivo in r["motivo"]


# ------------------------------------------------------------------ contrato de llegada (regla 09)

def test_contrato_de():
    assert capa2.contrato_de(f"{R}/wikidata_20260926T222617Z.jsonl") == f"{R}/_contrato_20260926T222617Z.json"


def test_lote_en_cuarentena_por_contrato_no_se_ingiere():
    a = arch("T1", "s1")
    c = {"estado": "cuarentena", "sha256": "s1", "fallas_criticas": ["invalid op"]}
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {}, {a["ruta"]: c})
    assert (r["estado"], r["motivo"]) == ("cuarentena_contrato", "contrato: invalid op")


def test_contrato_aprobado_o_ausente_se_ingiere():
    a, b = arch("T1", "s1"), arch("T2", "s2")
    [ra, rb] = capa2.clasificar([a, b], {a["ruta"]: man("s1"), b["ruta"]: man("s2")}, {},
                                {a["ruta"]: {"estado": "aprobado", "sha256": "s1"}})
    assert ra["estado"] == rb["estado"] == "ingerido_bronze"


def test_veredicto_de_otro_contenido_no_aplica():
    """El veredicto es de un sha256: si el archivo cambió después, no se usa ese veredicto."""
    a = arch("T1", "s2")
    c = {"estado": "cuarentena", "sha256": "s1", "fallas_criticas": ["invalid op"]}
    [r] = capa2.clasificar([a], {a["ruta"]: man("s2")}, {}, {a["ruta"]: c})
    assert r["estado"] == "ingerido_bronze"
