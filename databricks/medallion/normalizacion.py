"""Normalización de nombres, países y ciudades para Silver y la resolución (regla 08).

Python puro, sin Spark: Silver lo usa en UDFs y los tests corren locales (tests/medallion).
Diseñado sobre los nombres reales del universo (fase 6, perfil del 2026-09-27): 1.163 entidades de
GLEIF, sus nombres alternativos y OpenSanctions AR.

Por cada nombre:
- norm: mayúsculas, sin acentos ni puntuación; las letras sueltas seguidas se juntan
  ("S. A." -> "SA", "F.C.I." -> "FCI"); "&" -> "Y".
- forma: forma jurídica final extraída ("SA", "SRL", "INC"...), o "".
- sin_forma: norm sin la forma jurídica final. Es lo que se compara entre fuentes.
- tokens: tokens de sin_forma sin palabras vacías, llevados a castellano (ENERGY -> ENERGIA): la
  SEC y GDELT traducen los nombres palabra por palabra.

Un nombre en escritura no latina (日産自動車株式会社) queda vacío: la resolución usa los nombres
alternativos de la entidad (GLEIF trae la versión en inglés como ALTERNATIVE_LANGUAGE_LEGAL_NAME).
"SUCURSAL ARGENTINA" tampoco: una sucursal tiene su propio LEI y no es la casa matriz.
"FCI" y "FIDEICOMISO FINANCIERO" no son forma jurídica: distinguen fondos, el principal generador
de falsos positivos del universo (OPTIMUM RENTA FIJA DINAMICA F.C.I. vs. ... ESTRATEGICA F.C.I.).
"""

import re
import unicodedata

# Formas jurídicas que se sacan del final del nombre, ya normalizadas (letras sueltas juntas).
# Se prueban de la más larga a la más corta y se repite (ALLARIA LEDESMA Y CIA SA -> ... Y CIA -> ...).
FORMAS = {
    # Argentina y países de habla hispana
    "SOCIEDAD ANONIMA UNIPERSONAL": "SAU", "SOCIEDAD ANONIMA": "SA", "SAU": "SAU", "SA": "SA",
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA": "SRL", "SRL": "SRL", "SOCIEDAD LIMITADA": "SL",
    "SOCIEDAD POR ACCIONES SIMPLIFICADA": "SAS", "SAS": "SAS",
    "SOCIEDAD EN COMANDITA POR ACCIONES": "SCA", "SCA": "SCA",
    "SAB DE CV": "SAB DE CV", "SA DE CV": "SA DE CV", "DE CV": "SA DE CV",
    "SAIC": "SA", "SACI": "SA", "SAICF": "SA", "SACIF": "SA", "SAICYF": "SA", "SACIFIA": "SA",
    "SAICA": "SA", "CIASA": "SA", "IC YF": "SA", "ICYF": "SA", "IC Y F": "SA", "CIYF": "SA", "AIC": "SA", "CI": "SA",
    "COOP LTDA": "COOP", "COOPERATIVA LIMITADA": "COOP", "LIMITADA": "LTDA", "LTDA": "LTDA",
    "Y CIA": "CIA", "Y COMPANIA": "CIA", "CIA": "CIA",
    "SL": "SL", "SLU": "SL",
    # Inglés
    "INCORPORATED": "INC", "INC": "INC", "CORPORATION": "CORP", "CORP": "CORP", "COMPANY": "CO",
    "CO": "CO", "LIMITED": "LTD", "LTD": "LTD", "LLC": "LLC", "LP": "LP", "PLC": "PLC",
    # Otros del universo de control
    "AKTIENGESELLSCHAFT": "AG", "AG": "AG", "GMBH": "GMBH", "SE": "SE", "NV": "NV", "BV": "BV",
    "SPA": "SPA", "AB": "AB",
}
_FORMAS_ORDEN = sorted(FORMAS, key=lambda f: -len(f.split()))

VACIAS = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "E", "THE", "OF", "AND", "TO", "A"}

# Inglés -> castellano, palabra por palabra (como traducen la SEC y GDELT). Solo palabras que
# aparecen en los nombres del universo; se amplía con evidencia, como alias.json en la fase 4.
EQUIVALENCIAS = {
    "BANK": "BANCO", "GROUP": "GRUPO", "FINANCIAL": "FINANCIERO", "ENERGY": "ENERGIA",
    "INVESTMENTS": "INVERSIONES", "INVESTMENT": "INVERSION", "REPRESENTATIONS": "REPRESENTACIONES",
    "TRANSPORTER": "TRANSPORTADORA", "SOUTH": "SUR", "NORTH": "NORTE", "GAS": "GAS",
    "INDUSTRIAL": "INDUSTRIAL", "INSURANCE": "SEGUROS", "SECURITIES": "VALORES",
    "PORT": "PUERTO", "OIL": "PETROLEO", "PETROLEUM": "PETROLEO", "FUND": "FONDO",
    "HOLDINGS": "HOLDING", "SERVICES": "SERVICIOS", "INVESTORS": "INVERSORES",
    "FRENCH": "FRANCES", "ARGENTINE": "ARGENTINA", "ARGENTINIAN": "ARGENTINA",
    "COMPANIA": "COMPANIA", "INDUSTRIES": "INDUSTRIAS", "CEMENT": "CEMENTO",
}


def _sin_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _juntar_letras(tokens: list[str]) -> list[str]:
    """Junta corridas de letras sueltas: S A U -> SAU, F C I -> FCI, J J HINRICHSEN -> JJ HINRICHSEN."""
    out, corrida = [], []
    for t in tokens:
        if len(t) == 1 and t.isalpha():
            corrida.append(t)
            continue
        if corrida:
            out.append("".join(corrida))
            corrida = []
        out.append(t)
    if corrida:
        out.append("".join(corrida))
    return out


def norm(nombre: str | None) -> str:
    if not nombre:
        return ""
    s = _sin_acentos(nombre).upper().replace("&", " & ")
    tokens = _juntar_letras(re.sub(r"[^A-Z0-9&]+", " ", s).split())
    return " ".join("Y" if t == "&" else t for t in tokens)


def separar_forma(n: str) -> tuple[str, str]:
    """(sin_forma, forma) sobre un nombre ya normalizado. Nunca saca el primer token."""
    formas = []
    while True:
        for f in _FORMAS_ORDEN:
            if n.endswith(" " + f):
                n = n[: -len(f) - 1]
                formas.append(FORMAS[f])
                break
        else:
            break
    return n, (formas[-1] if formas else "")


def tokens(sin_forma: str) -> list[str]:
    return [EQUIVALENCIAS.get(t, t) for t in sin_forma.split() if t not in VACIAS]


def nombre(nombre_crudo: str | None) -> dict:
    n = norm(nombre_crudo)
    sin_forma, forma = separar_forma(n)
    return {"norm": n, "sin_forma": sin_forma, "forma": forma, "tokens": tokens(sin_forma)}


# ------------------------------------------------------------------ países (ISO 3166-1 alfa-2)

# Códigos de EDGAR que aparecen en el universo (stateOfIncorporation, stateOrCountry). Los estados
# de EE. UU. son dos letras: van a "US".
EDGAR = {"C1": "AR", "O5": "MX", "X3": "UY", "U3": "ES", "N4": "LU", "D0": "BM", "E9": "KY",
         "K3": "GB", "X0": "GB", "A0": "CA", "F4": "FR", "2M": "DE", "L2": "IL", "P7": "NL"}
ESTADOS_US = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
                 "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
NOMBRES_PAIS = {"ARGENTINA": "AR", "MEXICO": "MX", "URUGUAY": "UY", "SPAIN": "ES", "LUXEMBOURG": "LU",
                "UNITED STATES": "US", "USA": "US", "BRAZIL": "BR", "BRASIL": "BR", "CHILE": "CL"}


def pais(valor: str | None, fuente: str) -> str | None:
    if not valor:
        return None
    v = valor.strip().upper()
    if fuente == "gleif":            # jurisdicción: "AR", "US-DE"
        return v.split("-")[0] or None
    if fuente == "sec_edgar":        # código EDGAR o nombre del país
        if v in EDGAR:
            return EDGAR[v]
        if v in ESTADOS_US:
            return "US"
        return NOMBRES_PAIS.get(_sin_acentos(v))
    if len(v) == 2 and v.isalpha():  # OpenSanctions (minúsculas) y Wikidata
        return v
    return NOMBRES_PAIS.get(_sin_acentos(v))


# ------------------------------------------------------------------ ciudades

CIUDADES = {
    # La Ciudad de Buenos Aires aparece de 10 maneras en GLEIF; la provincia no se distingue en
    # el texto libre de la ciudad, así que "BUENOS AIRES" también cae acá (ciudad es una señal débil).
    "CABA": "BUENOS AIRES", "CAPITAL FEDERAL": "BUENOS AIRES", "CIUDAD AUTONOMA BUENOS AIRES": "BUENOS AIRES",
    "CIUDAD AUTONOMA DE BUENOS AIRES": "BUENOS AIRES", "CIUDAD AUTONOMA DE BS AS": "BUENOS AIRES",
    "CIUDAD DE BUENOS AIRES": "BUENOS AIRES", "CITY OF BUENOS AIRES": "BUENOS AIRES",
    "BS AS": "BUENOS AIRES", "BUENOS AIRES": "BUENOS AIRES",
}


def ciudad(valor: str | None) -> str | None:
    if not valor:
        return None
    v = " ".join(re.sub(r"[^A-Z ]+", " ", _sin_acentos(valor).upper()).split())  # saca códigos postales
    if not v or v in {"N A", "NA"} or v in NOMBRES_PAIS:   # la SEC pone "ARGENTINA" como ciudad (TGS)
        return None
    for k in sorted(CIUDADES, key=len, reverse=True):
        if v == k or v.endswith(" " + k) or v.startswith(k + " "):
            return CIUDADES[k]
    return v


# ------------------------------------------------------------------ identificadores

def lei_valido(lei: str | None) -> bool:
    """ISO 17442: 20 caracteres alfanuméricos y dígitos de control mod 97 == 1 (ISO 7064).

    En el universo fallan 68 LEI de la LOU argentina (5791..., emitidos en 2015), todos ANNULLED en
    GLEIF: no van a cuarentena (son el registro oficial), se marcan y no se usan como candidatos.
    """
    if not lei or not re.fullmatch(r"[0-9A-Z]{18}[0-9]{2}", lei):
        return False
    return int("".join(str(int(c, 36)) for c in lei)) % 97 == 1
