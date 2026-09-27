"""Normalización de nombres, países, ciudades y LEI (regla 08). Casos reales del universo."""

import pytest

import normalizacion as N


@pytest.mark.parametrize("crudo,norm,sin_forma,forma", [
    ("YPF SOCIEDAD ANONIMA", "YPF SOCIEDAD ANONIMA", "YPF", "SA"),
    ("CENTRAL PUERTO S.A.", "CENTRAL PUERTO SA", "CENTRAL PUERTO", "SA"),
    ("FERTIL PAMPA S.A.U.", "FERTIL PAMPA SAU", "FERTIL PAMPA", "SAU"),
    ("TETRA PAK SRL", "TETRA PAK SRL", "TETRA PAK", "SRL"),
    ("PEPSICO DE ARGENTINA SOCIEDAD DE RESPONSABILIDAD LIMITADA", None, "PEPSICO DE ARGENTINA", "SRL"),
    ("MICHELIN ARGENTINA SA IC Y F", "MICHELIN ARGENTINA SA IC YF", "MICHELIN ARGENTINA", "SA"),
    ("ALLARIA LEDESMA Y CIA S A", "ALLARIA LEDESMA Y CIA SA", "ALLARIA LEDESMA", "CIA"),
    ("LOMA NEGRA C.I.A.S.A.", "LOMA NEGRA CIASA", "LOMA NEGRA", "SA"),
    ("Vista Energy, S.A.B. de C.V.", "VISTA ENERGY SAB DE CV", "VISTA ENERGY", "SAB DE CV"),
    ("FORD MOTOR COMPANY", "FORD MOTOR COMPANY", "FORD MOTOR", "CO"),
    ("Pampa Energy Inc.", "PAMPA ENERGY INC", "PAMPA ENERGY", "INC"),
    ("J. J. HINRICHSEN S.A.", "JJ HINRICHSEN SA", "JJ HINRICHSEN", "SA"),
    ("S & C INVERSIONES S.A.", "S Y C INVERSIONES SA", "S Y C INVERSIONES", "SA"),
    ("OPTIMUM RENTA FIJA DINÁMICA F.C.I.", "OPTIMUM RENTA FIJA DINAMICA FCI", "OPTIMUM RENTA FIJA DINAMICA FCI", ""),
    ("Construtora Coesa S.A. - Sucursal Argentina", None, "CONSTRUTORA COESA SA SUCURSAL ARGENTINA", ""),
])
def test_nombre(crudo, norm, sin_forma, forma):
    r = N.nombre(crudo)
    if norm is not None:
        assert r["norm"] == norm
    assert (r["sin_forma"], r["forma"]) == (sin_forma, forma)


def test_forma_sola_no_se_saca():
    assert N.nombre("SA")["sin_forma"] == "SA"


def test_no_latino_queda_vacio():
    assert N.nombre("日産自動車株式会社")["norm"] == ""
    assert N.nombre(None) == {"norm": "", "sin_forma": "", "forma": "", "tokens": []}


@pytest.mark.parametrize("a,b", [
    # Traducciones de la SEC contra el nombre legal de GLEIF: mismos tokens canónicos
    ("Pampa Energy Inc.", "PAMPA ENERGIA S.A."),
    ("IRSA INVESTMENTS & REPRESENTATIONS INC", "IRSA INVERSIONES Y REPRESENTACIONES SOCIEDAD ANONIMA"),
    ("Vista Energy, S.A.B. de C.V.", "VISTA ENERGIA SA"),
])
def test_tokens_traducidos_iguales(a, b):
    assert N.nombre(a)["tokens"] == N.nombre(b)["tokens"]


@pytest.mark.parametrize("a,b", [
    ("Macro Bank Inc.", "BANCO MACRO S.A."),                          # otro orden
    ("GAS TRANSPORTER OF THE SOUTH INC", "TRANSPORTADORA DE GAS DEL SUR S.A."),
])
def test_tokens_traducidos_mismo_conjunto(a, b):
    assert set(N.nombre(a)["tokens"]) == set(N.nombre(b)["tokens"])


def test_fondos_no_se_confunden():
    a = N.nombre("OPTIMUM RENTA FIJA DINÁMICA F.C.I.")["tokens"]
    b = N.nombre("OPTIMUM RENTA FIJA ESTRATEGICA F.C.I.")["tokens"]
    assert a != b and "FCI" in a


@pytest.mark.parametrize("valor,fuente,iso", [
    ("AR", "gleif", "AR"), ("US-DE", "gleif", "US"),
    ("C1", "sec_edgar", "AR"), ("O5", "sec_edgar", "MX"), ("DE", "sec_edgar", "US"),
    ("Argentina", "sec_edgar", "AR"), ("ar", "opensanctions", "AR"), ("AR", "wikidata", "AR"),
    (None, "gleif", None), ("", "sec_edgar", None), ("ZZ9", "sec_edgar", None),
])
def test_pais(valor, fuente, iso):
    assert N.pais(valor, fuente) == iso


@pytest.mark.parametrize("valor,esperado", [
    ("CABA", "BUENOS AIRES"), ("CIUDAD AUTÓNOMA DE BUENOS AIRES", "BUENOS AIRES"),
    ("Capital Federal", "BUENOS AIRES"), ("C1054AAA BUENOS AIRES", "BUENOS AIRES"),
    ("BUENOS AIRES 1364 AR", "BUENOS AIRES"), ("CITY OF BUENOS AIRES", "BUENOS AIRES"),
    ("Rosario", "ROSARIO"), ("N/A", None), (None, None), ("ARGENTINA", None),
])
def test_ciudad(valor, esperado):
    assert N.ciudad(valor) == esperado


@pytest.mark.parametrize("lei,valido", [
    ("20S05OYHG0MQM4VUIC57", True),     # Ford Motor Company
    ("254900BVL72C9S31GJ22", True),     # MAX CAPITAL S.A.
    ("20S05OYHG0MQM4VUIC58", False),    # dígito de control alterado
    ("579100BKDDEFFCCHB090", False),    # LOU argentina 2015, ANNULLED en GLEIF
    ("20S05OYHG0MQM4VUIC5", False), ("20s05oyhg0mqm4vuic57", False), (None, False),
])
def test_lei_valido(lei, valido):
    assert N.lei_valido(lei) is valido
