"""Capa 2 de idempotencia de Bronze (D6)."""

import pytest

import capa2

R = "/Volumes/entity360/landing/raw/wikidata/ingest_date=2026-09-26"


def arch(ts, sha, lineas=20):
    return {"ruta": f"{R}/wikidata_{ts}.jsonl", "sha256": sha, "lineas": lineas}


def man(sha, registros=20):
    return {"sha256": sha, "registros": registros}


def ok(sha):
    return {"estado": "aprobado", "sha256": sha}


def aprobados(*archivos):
    return {a["ruta"]: ok(a["sha256"]) for a in archivos}


def test_manifest_de():
    assert capa2.manifest_de(f"{R}/wikidata_20260926T222617Z.jsonl") == f"{R}/_manifest_20260926T222617Z.json"
    assert capa2.manifest_de("/x/sqlserver_cdc/d=1/sqlserver_cdc_20260925T215645Z.jsonl").endswith("/_manifest_20260925T215645Z.json")


def test_lote_nuevo():
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {}, aprobados(a))
    assert r["estado"] == "ingerido_bronze"


def test_sin_manifest_falla_el_lote_entero():
    a, b = arch("T1", "s1"), arch("T2", "s2")
    with pytest.raises(capa2.ManifestPendiente, match="T2"):
        capa2.clasificar([a, b], {a["ruta"]: man("s1"), b["ruta"]: None}, {}, aprobados(a, b))


def test_reenvio_identico_con_otro_nombre_es_duplicado():
    viejo, nuevo = arch("T1", "s1"), arch("T2", "s1")
    [r] = capa2.clasificar([nuevo], {nuevo["ruta"]: man("s1")}, {"s1": viejo["ruta"]}, aprobados(nuevo))
    assert r["estado"] == "duplicado" and "wikidata_T1.jsonl" in r["motivo"]


def test_mismo_archivo_reprocesado_no_es_duplicado():
    """Checkpoint borrado: el mismo archivo vuelve a entrar; el MERGE por (sha256, linea) no duplica."""
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {"s1": a["ruta"]}, aprobados(a))
    assert r["estado"] == "ingerido_bronze"


def test_duplicado_dentro_del_mismo_lote():
    a, b = arch("T1", "s1"), arch("T2", "s1")
    r = capa2.clasificar([b, a], {a["ruta"]: man("s1"), b["ruta"]: man("s1")}, {}, aprobados(b, a))
    assert [x["estado"] for x in r] == ["ingerido_bronze", "duplicado"]


@pytest.mark.parametrize("m,motivo", [(man("otro"), "sha256"), (man("s1", registros=19), "19")])
def test_errores(m, motivo):
    a = arch("T1", "s1")
    [r] = capa2.clasificar([a], {a["ruta"]: m}, {}, aprobados(a))
    assert r["estado"] == "error" and motivo in r["motivo"]


# ------------------------------------------------------------------ contrato de llegada (regla 09, ADR 0006)

def test_contrato_de():
    assert capa2.contrato_de(f"{R}/wikidata_20260926T222617Z.jsonl") == f"{R}/_contrato_20260926T222617Z.json"


def test_lote_en_cuarentena_por_contrato_no_se_ingiere():
    a = arch("T1", "s1")
    c = {"estado": "cuarentena", "sha256": "s1", "fallas_criticas": ["invalid op"]}
    [r] = capa2.clasificar([a], {a["ruta"]: man("s1")}, {}, {a["ruta"]: c})
    assert (r["estado"], r["motivo"]) == ("cuarentena_contrato", "contrato: invalid op")


def test_cuarentena_gana_sobre_el_error_de_manifest():
    """Un archivo truncado: el contrato ya lo apartó; Bronze no lo marca como error a revisar."""
    a = arch("T1", "s-truncado", lineas=10)
    c = {"estado": "cuarentena", "sha256": "s-truncado", "fallas_criticas": ["sha256 del manifest"]}
    [r] = capa2.clasificar([a], {a["ruta"]: man("s-original")}, {}, {a["ruta"]: c})
    assert r["estado"] == "cuarentena_contrato"


def test_sin_veredicto_falla_el_lote_entero():
    a, b = arch("T1", "s1"), arch("T2", "s2")
    with pytest.raises(capa2.ContratoPendiente, match="sin veredicto.*T2"):
        capa2.clasificar([a, b], {a["ruta"]: man("s1"), b["ruta"]: man("s2")}, {}, {a["ruta"]: ok("s1"), b["ruta"]: None})


def test_veredicto_de_otro_contenido_falla():
    """El veredicto es de un sha256: si el archivo cambió después, hay que volver a verificarlo."""
    a = arch("T1", "s2")
    with pytest.raises(capa2.ContratoPendiente, match="otro contenido"):
        capa2.clasificar([a], {a["ruta"]: man("s2")}, {}, {a["ruta"]: ok("s1")})


def test_manifest_pendiente_antes_que_contrato():
    a = arch("T1", "s1")
    with pytest.raises(capa2.ManifestPendiente):
        capa2.clasificar([a], {a["ruta"]: None}, {}, {a["ruta"]: None})
