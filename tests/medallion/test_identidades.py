"""Resolución de identidades (regla 08): blocking, score, clusters, entity_id estable y golden record.

Los nombres son del universo real (GLEIF, OpenSanctions), pero los casos no son del set de
validación: las decisiones de la parte A y la parte B no se prueban acá.
"""

import identidades as I

LEI_A = "5493001KJTIIGC8Y1R12"   # formato válido; los tests no dependen del dígito de control
LEI_B = "529900T8BM49AURSDO55"


def reg(fuente, id_, nombres, paises=("AR",), ciudad=None, leis=(), ciks=(), tickers=(), dominios=(),
        lei_firme=None, datos=None):
    if lei_firme is None:
        lei_firme = fuente == "gleif"
    return {"clave": f"{fuente}:{id_}", "fuente": fuente, "id_fuente": id_, "nombres": list(nombres),
            "paises": list(paises), "ciudad": ciudad, "leis": list(leis), "ciks": list(ciks),
            "tickers": list(tickers), "dominios": list(dominios), "lei_firme": lei_firme, "datos": datos or {}}


# ------------------------------------------------------------------ score

def test_mismo_nombre_y_pais_se_acepta():
    a = reg("gleif", LEI_A, ["CENTRAL PUERTO S.A."], leis=[LEI_A], ciudad="BUENOS AIRES")
    b = reg("opensanctions", "x1", ["Central Puerto SA"])
    p = I.puntuar(a, b)
    assert p["decision"] == "aceptado"
    assert p["contribuciones"]["nombre"] == I.PESOS["nombre"]
    assert p["contribuciones"]["pais"] == I.PESOS["pais_igual"]


def test_series_de_fondos_distintas_no_se_aceptan():
    a = reg("gleif", "L1", ["FIDEICOMISO FINANCIERO CONSUBOND XXXV"], lei_firme=False)
    b = reg("gleif", "L2", ["FIDEICOMISO FINANCIERO CONSUBOND XXXVI"])
    p = I.puntuar(a, b)
    assert p["contribuciones"]["numeros_distintos"] == I.PESOS["numeros_distintos"]
    assert p["decision"] != "aceptado"


def test_fondo_contra_empresa_resta():
    a = reg("opensanctions", "x", ["OPTIMUM RENTA FIJA DINAMICA F.C.I."])
    b = reg("gleif", "L", ["OPTIMUM ASSET MANAGEMENT S.A."])
    assert I.puntuar(a, b)["contribuciones"]["fondo_vs_no_fondo"] == I.PESOS["fondo_vs_no_fondo"]


def test_pais_distinto_resta():
    a = reg("gleif", "L", ["TETRA PAK SRL"], paises=["AR"])
    b = reg("opensanctions", "x", ["Tetra Pak Ltd"], paises=["GB"])
    p = I.puntuar(a, b)
    assert p["contribuciones"]["pais"] == I.PESOS["pais_distinto"]
    assert p["decision"] == "rechazado"


def test_ticker_y_dominio_suman():
    a = reg("sec_edgar", "1", ["Ternium S.A."], tickers=["TX"], dominios=["ternium.com"], ciks=[1])
    b = reg("wikidata", "Q1", ["Ternium"], tickers=["TX"], dominios=["ternium.com"])
    c = I.puntuar(a, b)["contribuciones"]
    assert c["ticker"] == I.PESOS["ticker"] and c["dominio"] == I.PESOS["dominio"]


def test_identificador_compartido_es_deterministico():
    a = reg("gleif", LEI_A, ["NOMBRE LEGAL SA"], leis=[LEI_A])
    b = reg("opensanctions", "x", ["Otro nombre totalmente distinto"], leis=[LEI_A])
    p = I.puntuar(a, b)
    assert (p["decision"], p["motivo"]) == ("determinístico", "LEI compartido")


def test_veto_por_lei_firme_o_cik_distinto():
    a = reg("wikidata", "Q1", ["Banco X"], leis=[LEI_A])
    b = reg("gleif", LEI_B, ["BANCO X SA"], leis=[LEI_B])
    assert I.puntuar(a, b)["decision"] == "veto"
    c = reg("sec_edgar", "1", ["Banco X"], ciks=[1])
    d = reg("wikidata", "Q2", ["Banco X"], ciks=[2])
    assert I.puntuar(c, d)["motivo"] == "CIK distintos"


def test_lei_anulado_no_veta():
    """Un LEI anulado (duplicado dado de baja por GLEIF) no es firme: se puede unir con su gemelo."""
    a = reg("gleif", LEI_A, ["ACME SA"], leis=[LEI_A], lei_firme=False)
    b = reg("gleif", LEI_B, ["ACME S.A."], leis=[LEI_B])
    assert I.puntuar(a, b)["decision"] == "aceptado"


# ------------------------------------------------------------------ blocking

def test_blocking_solo_pares_comparables():
    regs = [reg("gleif", "L1", ["ACME SA"]), reg("gleif", "L2", ["ACME SRL"]),
            reg("gleif", "L3", ["ACME SAU"], lei_firme=False), reg("opensanctions", "x", ["Acme"]),
            reg("sec_edgar", "1", ["Acme Inc"], paises=["US"]), reg("sec_edgar", "2", ["Acme Corp"], paises=["US"])]
    pares, resumen = I.pares_candidatos(regs)
    assert ("gleif:L1", "gleif:L2") not in pares        # dos LEI firmes: la restricción ya decide
    assert ("gleif:L1", "gleif:L3") in pares            # duplicado de GLEIF
    assert ("sec_edgar:1", "sec_edgar:2") not in pares  # misma fuente
    assert ("gleif:L1", "sec_edgar:1") in pares         # otro país, pero comparten un token poco frecuente
    assert pares[("gleif:L1", "opensanctions:x")] == {"pais_prefijo", "token"}
    assert resumen["pares"] == len(pares)


def test_token_frecuente_no_bloquea():
    regs = [reg("gleif", f"L{i}", [f"BANCO NUMERO{i} SA"]) for i in range(I.MAX_FRECUENCIA_TOKEN + 1)]
    regs.append(reg("opensanctions", "x", ["Banco Zeta"], paises=["CU"]))
    pares, _ = I.pares_candidatos(regs)
    assert not any("opensanctions:x" in p for p in pares)


def test_pares_por_identificador():
    regs = [reg("sec_edgar", "7", ["A"], ciks=[7]), reg("wikidata", "Q", ["B"], ciks=[7], leis=[LEI_A]),
            reg("gleif", LEI_A, ["C"], leis=[LEI_A])]
    assert I.pares_por_identificador(regs) == {("sec_edgar:7", "wikidata:Q"), ("gleif:" + LEI_A, "wikidata:Q")}


# ------------------------------------------------------------------ clusters

def par(a, b, decision, puntaje=80):
    return {"clave_a": a, "clave_b": b, "decision": decision, "puntaje": puntaje, "motivo": None}


def test_clusters_transitivos_por_identificador():
    regs = [reg("sec_edgar", "7", ["A"], ciks=[7]), reg("wikidata", "Q", ["B"], ciks=[7], leis=[LEI_A]),
            reg("gleif", LEI_A, ["C"], leis=[LEI_A])]
    raices, conflictos = I.clusters(regs, [par("sec_edgar:7", "wikidata:Q", "determinístico"),
                                           par("gleif:" + LEI_A, "wikidata:Q", "determinístico")])
    assert len(set(raices.values())) == 1 and not conflictos


def test_cluster_nunca_une_dos_lei_firmes():
    """x se parece a los dos bancos: se une al de mayor puntaje y el otro par queda como conflicto."""
    regs = [reg("gleif", LEI_A, ["A"], leis=[LEI_A]), reg("gleif", LEI_B, ["B"], leis=[LEI_B]),
            reg("opensanctions", "x", ["X"])]
    raices, conflictos = I.clusters(regs, [par("gleif:" + LEI_A, "opensanctions:x", "aceptado", 75),
                                           par("gleif:" + LEI_B, "opensanctions:x", "aceptado", 90)])
    assert raices["opensanctions:x"] == raices["gleif:" + LEI_B]
    assert raices["gleif:" + LEI_A] != raices["gleif:" + LEI_B]
    assert [(c["clave_a"], c["motivo"]) for c in conflictos] == [("gleif:" + LEI_A, "uniría LEI firmes distintos")]


def test_revisar_y_rechazado_no_unen():
    regs = [reg("gleif", "L", ["A"]), reg("opensanctions", "x", ["A"]), reg("wikidata", "Q", ["A"])]
    raices, _ = I.clusters(regs, [par("gleif:L", "opensanctions:x", "revisar", 60),
                                  par("gleif:L", "wikidata:Q", "rechazado", 10)])
    assert len(set(raices.values())) == 3


# ------------------------------------------------------------------ entity_id estable

def grupos_de(*miembros_por_cluster):
    return {m[0]["clave"]: list(m) for m in miembros_por_cluster}


def test_entity_id_nuevo_es_hash_del_ancla_y_reproducible():
    g = reg("gleif", LEI_A, ["A"], leis=[LEI_A])
    o = reg("opensanctions", "x", ["A"])
    ids1 = I.entity_ids(grupos_de([o, g]), {})
    ids2 = I.entity_ids(grupos_de([g, o]), {})
    assert list(ids1.values()) == list(ids2.values())
    assert I.ancla([o, g]) == "gleif:" + LEI_A


def test_entity_id_se_conserva_al_sumar_un_registro():
    g = reg("gleif", LEI_A, ["A"], leis=[LEI_A])
    o = reg("opensanctions", "x", ["A"])
    ids = I.entity_ids(grupos_de([g, o]), {"gleif:" + LEI_A: "E-VIEJO"})
    assert list(ids.values()) == ["E-VIEJO"]


def test_division_el_id_queda_en_el_cluster_con_mas_miembros_previos():
    a, b, c = reg("gleif", "L1", ["A"]), reg("opensanctions", "x", ["A"]), reg("wikidata", "Q", ["A"])
    previos = {"gleif:L1": "E1", "opensanctions:x": "E1", "wikidata:Q": "E1"}
    ids = I.entity_ids({"gleif:L1": [a, b], "wikidata:Q": [c]}, previos)
    assert ids["gleif:L1"] == "E1" and ids["wikidata:Q"] not in ("E1",)


# ------------------------------------------------------------------ golden record

def test_golden_supervivencia_y_procedencia():
    firme = reg("gleif", LEI_A, ["ACME S.A."], leis=[LEI_A], ciudad="BUENOS AIRES",
                datos={"estado_entidad": "ACTIVE", "estado_registro": "ISSUED", "forma_juridica": "SA"})
    anulado = reg("gleif", LEI_B, ["ACME SOCIEDAD ANONIMA"], leis=[LEI_B], lei_firme=False)
    sec = reg("sec_edgar", "9", ["Acme Inc."], paises=["US"], ciks=[9], tickers=["ACM"],
              datos={"sitio_web": "https://acme.example"})
    os_ = reg("opensanctions", "x", ["Acme"], datos={"sancionada": True})
    g = I.golden("E1", [sec, os_, anulado, firme])
    assert (g["nombre"], g["lei"], g["cik"], g["ticker"], g["pais"]) == ("ACME S.A.", LEI_A, 9, "ACM", "AR")
    assert g["procedencia"]["nombre"] == "gleif:" + LEI_A and g["procedencia"]["cik"] == "sec_edgar:9"
    assert g["sancionada"] and g["en_listas_de_riesgo"] and g["duplicados_en_gleif"] == 1
    assert g["fuentes"] == ["gleif", "opensanctions", "sec_edgar"] and g["registros"] == 4
