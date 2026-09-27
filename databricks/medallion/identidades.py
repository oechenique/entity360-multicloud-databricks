"""Resolución de identidades (regla 08, pasos 1 a 5): blocking, score, clusters y golden record.

Python puro, sin Spark: la tarea `resolucion` lo usa en UDFs y en el driver, y los tests corren
locales (tests/medallion). Todo es por reglas auditables, sin modelos de ML: cada par guarda la
contribución de cada señal a su puntaje.

Un **registro** es un dict con:
    clave        "<fuente>:<id>" (gleif:<LEI>, sec_edgar:<CIK>, opensanctions:<id>, wikidata:<QID>,
                 gdelt:<clave de alias.json>). Es la misma clave que usa el set de validación.
    fuente, id_fuente, nombres (lista, el primero es el principal), paises (lista ISO), ciudad,
    leis, lei_firme (bool, solo GLEIF), ciks, tickers, dominios, datos (atributos para el golden).

Decisiones (pesos y umbrales **iniciales, sin calibrar**: se calibran con la mitad del set de
validación, D11):
- **Determinístico:** dos registros que comparten un LEI o un CIK son la misma entidad, salvo que el
  identificador llegue solo desde Wikidata: ahí es una señal fuerte (`id_wikidata`), no una unión
  automática ni un veto (D11: Wikidata es señal, no verdad; el ítem de la marca Flow trae el LEI de
  Cablevisión Holding).
- **Restricción de cluster:** nunca dos LEI firmes distintos ni dos CIK distintos. Un LEI es firme si
  su dígito de control es válido y su registro en GLEIF no está ANNULLED ni DUPLICATE (esos son
  duplicados que el propio GLEIF dio de baja: 63 de los 68 anulados tienen un gemelo vigente).
- **Gemelo de LEI:** dos registros de GLEIF con la misma base (los 18 caracteres antes de los dígitos
  de control) son una reemisión de la LOU argentina (2015): suman `gemelo_lei`.
- **Empates:** si un registro empata en su mejor puntaje con candidatos de LEI firmes distintos, esos
  pares van a revisión: nunca se une por el orden de las claves.
- **Blocking:** país + prefijo del nombre, tokens poco frecuentes e identificadores débiles (ticker,
  dominio). Solo se comparan pares dentro de un bloque.
- **Pares que se comparan:** de fuentes distintas, o dos registros de GLEIF si uno no es firme (el
  duplicado de GLEIF). Dos LEI firmes o dos CIK distintos no se comparan: la restricción ya decide.
"""

import hashlib
import re
from itertools import combinations

from rapidfuzz import fuzz

import normalizacion as N

# ------------------------------------------------------------------ pesos y umbrales (sin calibrar)

PESOS = {
    "nombre": 60,               # similitud de nombre: 0 puntos en 70/100 o menos, 60 en 100/100
    "pais_igual": 10,
    "pais_distinto": -20,       # los dos tienen país y no comparten ninguno
    "ciudad_igual": 5,
    "ticker": 30,
    "dominio": 30,
    "fondo_vs_no_fondo": -30,   # FCI, fideicomiso o fondo contra una empresa operativa
    "numeros_distintos": -20,   # SERIE 1 contra SERIE 2, FIDEICOMISO XXXV contra XXXVI
    "id_wikidata": 40,          # LEI o CIK compartido que llega solo desde Wikidata (señal, no unión)
    "gemelo_lei": 30,           # dos registros de GLEIF con la misma base de LEI (reemisión)
}
NOMBRE_PISO = 70
UMBRAL_ACEPTAR = 70
UMBRAL_REVISAR = 50

MAX_FRECUENCIA_TOKEN = 25   # un token en más registros que esto no sirve de bloque (BANCO, GRUPO...)
MAX_TAMANO_BLOQUE = 200     # bloques más grandes se descartan (se cuentan en el resumen)

ESTADOS_NO_FIRMES = {"ANNULLED", "DUPLICATE"}
FUENTES_SENAL = {"wikidata"}   # sus identificadores son señal, no unión ni veto (D11)
# Alias que no identifican a nadie: OpenSanctions los lista para UTEs y consorcios ("Ute", "The Joint
# Venture"). Un nombre hecho solo de estos tokens se ignora.
TOKENS_GENERICOS = {"UTE", "JOINT", "VENTURE", "CONSORCIO", "CONSORTIUM"}
MIN_TOKENS_CONJUNTO = 2        # token_set_ratio solo si los dos nombres tienen 2 tokens significativos
FONDO = {"FCI", "FONDO", "FIDEICOMISO", "FF"}
ROMANOS = re.compile(r"^[IVXLC]+$")


# ------------------------------------------------------------------ nombres

def variantes(nombres: list[str]) -> list[tuple[str, str]]:
    """(tokens canónicos ordenados, nombre sin forma jurídica) de cada nombre no vacío y no genérico."""
    out = []
    for n in nombres:
        x = N.nombre(n)
        if x["sin_forma"] and not set(x["tokens"]) <= TOKENS_GENERICOS:
            v = (" ".join(sorted(x["tokens"])), x["sin_forma"])
            if v not in out:
                out.append(v)
    return out


def _var(r: dict) -> list[tuple[str, str]]:
    if "_var" not in r:
        r["_var"] = variantes(r["nombres"])
    return r["_var"]


def _significativos(tokens: str) -> int:
    return sum(1 for t in tokens.split() if t not in TOKENS_GENERICOS)


def similitud(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> float:
    """Máximo sobre pares de variantes de max(token_set_ratio de tokens, ratio del nombre).

    token_set_ratio da 100 cuando un nombre está contenido en el otro: solo se usa si los dos tienen al
    menos MIN_TOKENS_CONJUNTO tokens significativos (si no, "UTE" empataba con cualquier UTE)."""
    def par(ta, sa, tb, sb):
        r = fuzz.ratio(sa, sb)
        if min(_significativos(ta), _significativos(tb)) >= MIN_TOKENS_CONJUNTO:
            r = max(r, fuzz.token_set_ratio(ta, tb))
        return r
    return max((par(ta, sa, tb, sb) for ta, sa in a for tb, sb in b), default=0.0)


def _tokens(nombres: list[str]) -> set[str]:
    return {t for n in nombres for t in N.nombre(n)["tokens"]}


def _numeros(nombres: list[str]) -> set[str]:
    """Números arábigos y romanos del nombre principal (distinguen series de fondos y fideicomisos)."""
    toks = N.nombre(nombres[0])["tokens"] if nombres else []
    return {t for t in toks if t.isdigit() or (ROMANOS.match(t) and len(t) > 1)}


def es_fondo(nombres: list[str]) -> bool:
    return bool(FONDO & set(N.norm(nombres[0]).split())) if nombres else False


# ------------------------------------------------------------------ identificadores

def leis_firmes(r: dict) -> set[str]:
    """LEI que cuentan para la restricción de cluster y para el veto."""
    if r["fuente"] in FUENTES_SENAL:
        return set()
    if r["fuente"] == "gleif":
        return set(r["leis"]) if r.get("lei_firme") else set()
    return set(r["leis"])


def ciks_firmes(r: dict) -> set[int]:
    return set() if r["fuente"] in FUENTES_SENAL else set(r["ciks"])


def veto(a: dict, b: dict) -> str | None:
    """Motivo por el que dos registros no pueden ser la misma entidad, o None."""
    la, lb = leis_firmes(a), leis_firmes(b)
    if la and lb and not la & lb:
        return "LEI distintos"
    ca, cb = ciks_firmes(a), ciks_firmes(b)
    if ca and cb and not ca & cb:
        return "CIK distintos"
    return None


def comparte_id(a: dict, b: dict) -> str | None:
    """Identificador compartido que une sin puntaje (matching determinístico), o None.
    Si uno de los dos es de Wikidata no une: es la señal id_wikidata (comparte_id_senal)."""
    if a["fuente"] in FUENTES_SENAL or b["fuente"] in FUENTES_SENAL:
        return None
    if set(a["leis"]) & set(b["leis"]):
        return "LEI"
    if set(a["ciks"]) & set(b["ciks"]):
        return "CIK"
    return None


def comparte_id_senal(a: dict, b: dict) -> bool:
    """LEI o CIK compartido con un registro de Wikidata."""
    if a["fuente"] not in FUENTES_SENAL and b["fuente"] not in FUENTES_SENAL:
        return False
    return bool(set(a["leis"]) & set(b["leis"]) or set(a["ciks"]) & set(b["ciks"]))


def gemelos_lei(a: dict, b: dict) -> bool:
    """Dos registros de GLEIF con la misma base de LEI (18 caracteres) y distinto dígito de control."""
    if a["fuente"] != "gleif" or b["fuente"] != "gleif":
        return False
    return a["id_fuente"][:18] == b["id_fuente"][:18] and a["id_fuente"] != b["id_fuente"]


def comparable(a: dict, b: dict) -> bool:
    if a["fuente"] != b["fuente"]:
        return True
    return a["fuente"] == "gleif" and not (a.get("lei_firme") and b.get("lei_firme"))


# ------------------------------------------------------------------ blocking

def frecuencias(registros: list[dict]) -> dict[str, int]:
    """En cuántos registros aparece cada token (uno por registro)."""
    f: dict[str, int] = {}
    for r in registros:
        for t in _tokens(r["nombres"]):
            f[t] = f.get(t, 0) + 1
    return f


def claves_bloqueo(r: dict, frec: dict[str, int]) -> set[str]:
    claves = set()
    for n in r["nombres"]:
        toks = N.nombre(n)["tokens"]
        if toks:
            for p in r["paises"] or ["??"]:
                claves.add(f"pais_prefijo:{p}:{toks[0][:4]}")
        for t in toks:
            if len(t) >= 3 and not t.isdigit() and frec.get(t, 0) <= MAX_FRECUENCIA_TOKEN:
                claves.add(f"token:{t}")
    claves |= {f"ticker:{t}" for t in r["tickers"]}
    claves |= {f"dominio:{d}" for d in r["dominios"]}
    return claves


def pares_candidatos(registros: list[dict]) -> tuple[dict[tuple[str, str], set[str]], dict]:
    """Pares (clave_a, clave_b) con a < b dentro de algún bloque, con los bloques que los juntan."""
    frec = frecuencias(registros)
    bloques: dict[str, list[str]] = {}
    for r in registros:
        for k in claves_bloqueo(r, frec):
            bloques.setdefault(k, []).append(r["clave"])
    por_clave = {r["clave"]: r for r in registros}
    pares: dict[tuple[str, str], set[str]] = {}
    grandes = 0
    for k, miembros in bloques.items():
        if len(miembros) > MAX_TAMANO_BLOQUE:
            grandes += 1
            continue
        for x, y in combinations(sorted(set(miembros)), 2):
            if comparable(por_clave[x], por_clave[y]):
                pares.setdefault((x, y), set()).add(k.split(":")[0])
    return pares, {"bloques": len(bloques), "bloques_descartados_por_tamano": grandes, "pares": len(pares)}


# ------------------------------------------------------------------ score

def senales(a: dict, b: dict) -> dict:
    """Lo que el puntaje mira de un par, sin pesos (calibrar.py las calcula una vez y prueba pesos)."""
    pa, pb = set(a["paises"]), set(b["paises"])
    return {"veto": veto(a, b), "ident": comparte_id(a, b), "sim": similitud(_var(a), _var(b)),
            "pais": None if not (pa and pb) else bool(pa & pb),
            "ciudad": bool(a.get("ciudad")) and a.get("ciudad") == b.get("ciudad"),
            "ticker": bool(set(a["tickers"]) & set(b["tickers"])),
            "dominio": bool(set(a["dominios"]) & set(b["dominios"])),
            "fondo": es_fondo(a["nombres"]) != es_fondo(b["nombres"]),
            "numeros": _numeros(a["nombres"]) != _numeros(b["nombres"]),
            "id_wikidata": comparte_id_senal(a, b), "gemelo_lei": gemelos_lei(a, b)}


def contribuciones(s: dict, pesos: dict | None = None, piso: float | None = None) -> dict:
    p = pesos or PESOS
    piso = NOMBRE_PISO if piso is None else piso
    c = {"nombre": round(p["nombre"] * min(1.0, max(0.0, (s["sim"] - piso) / (100 - piso))))}
    if s["pais"] is not None:
        c["pais"] = p["pais_igual"] if s["pais"] else p["pais_distinto"]
    for senal, peso in (("ciudad", "ciudad_igual"), ("ticker", "ticker"), ("dominio", "dominio"),
                        ("id_wikidata", "id_wikidata"), ("gemelo_lei", "gemelo_lei")):
        if s[senal]:
            c[senal] = p[peso]
    if s["fondo"]:
        c["fondo_vs_no_fondo"] = p["fondo_vs_no_fondo"]
    if s["numeros"]:
        c["numeros_distintos"] = p["numeros_distintos"]
    return c


def decidir(s: dict, pesos: dict | None = None, piso: float | None = None,
            aceptar: float | None = None, revisar: float | None = None) -> dict:
    """decision: determinístico | aceptado | revisar | rechazado | veto."""
    if s["veto"]:
        return {"puntaje": None, "similitud_nombre": None, "contribuciones": {}, "decision": "veto",
                "motivo": s["veto"]}
    c = contribuciones(s, pesos, piso)
    puntaje = sum(c.values())
    aceptar = UMBRAL_ACEPTAR if aceptar is None else aceptar
    revisar = UMBRAL_REVISAR if revisar is None else revisar
    motivo = None
    if s["ident"]:
        decision, motivo = "determinístico", f"{s['ident']} compartido"
    elif puntaje >= aceptar:
        decision = "aceptado"
    elif puntaje >= revisar:
        decision = "revisar"
    else:
        decision = "rechazado"
    return {"puntaje": puntaje, "similitud_nombre": round(s["sim"], 1), "contribuciones": c,
            "decision": decision, "motivo": motivo}


def puntuar(a: dict, b: dict) -> dict:
    """Puntaje del par con la contribución de cada señal y la decisión (pesos del módulo)."""
    return decidir(senales(a, b))


def pares_por_identificador(registros: list[dict]) -> set[tuple[str, str]]:
    """Pares que comparten LEI o CIK aunque ningún bloque de nombre los junte (paso 1: determinístico)."""
    por_id: dict[str, list[str]] = {}
    for r in registros:
        for l in r["leis"]:
            por_id.setdefault(f"lei:{l}", []).append(r["clave"])
        for c in r["ciks"]:
            por_id.setdefault(f"cik:{c}", []).append(r["clave"])
    return {(x, y) for m in por_id.values() for x, y in combinations(sorted(set(m)), 2)}


# ------------------------------------------------------------------ clusters

def clusters(registros: list[dict], pares: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """Une los pares determinísticos y después los aceptados, de mayor a menor puntaje, sin violar la
    restricción (un LEI firme y un CIK por cluster). Los empates (empates()) no se unen: van a
    revisión junto con los conflictos. Devuelve (clave -> raíz, conflictos)."""
    por_clave = {r["clave"]: r for r in registros}
    padre = {k: k for k in por_clave}
    leis = {k: set(leis_firmes(r)) for k, r in por_clave.items()}
    ciks = {k: ciks_firmes(r) for k, r in por_clave.items()}

    def raiz(k):
        while padre[k] != k:
            padre[k] = padre[padre[k]]
            k = padre[k]
        return k

    orden = {"determinístico": 0, "aceptado": 1}
    empatados = empates(pares, por_clave)
    unibles = sorted((p for p in pares if p["decision"] in orden and (p["clave_a"], p["clave_b"]) not in empatados),
                     key=lambda p: (orden[p["decision"]], -(p["puntaje"] or 0), p["clave_a"], p["clave_b"]))
    conflictos = [{**p, "motivo": "empate: el mismo puntaje con candidatos de LEI firmes distintos"}
                  for p in pares if (p["clave_a"], p["clave_b"]) in empatados]
    for p in unibles:
        ra, rb = raiz(p["clave_a"]), raiz(p["clave_b"])
        if ra == rb:
            continue
        l, c = leis[ra] | leis[rb], ciks[ra] | ciks[rb]
        if len(l) > 1 or len(c) > 1:
            conflictos.append({**p, "motivo": "uniría " + ("LEI firmes distintos" if len(l) > 1 else "CIK distintos")})
            continue
        nueva, vieja = sorted((ra, rb))
        padre[vieja] = nueva
        leis[nueva], ciks[nueva] = l, c
    return {k: raiz(k) for k in por_clave}, conflictos


def empates(pares: list[dict], por_clave: dict[str, dict]) -> set[tuple[str, str]]:
    """Pares aceptados que empatan en el mejor puntaje de un registro con candidatos de LEI firmes
    distintos. Unir cualquiera sería elegir por el orden de las claves: van a revisión."""
    mejores: dict[str, list[tuple[int, str, tuple[str, str]]]] = {}
    for p in pares:
        if p["decision"] != "aceptado":
            continue
        for yo, otro in ((p["clave_a"], p["clave_b"]), (p["clave_b"], p["clave_a"])):
            mejores.setdefault(yo, []).append((p["puntaje"], otro, (p["clave_a"], p["clave_b"])))
    out = set()
    for yo, cands in mejores.items():
        tope = max(c[0] for c in cands)
        top = [c for c in cands if c[0] == tope]
        leis = {frozenset(leis_firmes(por_clave[otro])) for _, otro, _ in top if leis_firmes(por_clave[otro])}
        if len(leis) > 1:
            out |= {par for _, _, par in top}
    return out


PRIORIDAD_ANCLA = {"gleif": 0, "sec_edgar": 1, "wikidata": 2, "opensanctions": 3, "gdelt": 4}


def ancla(miembros: list[dict]) -> str:
    """El registro que da nombre al cluster: GLEIF firme primero, después por fuente y clave."""
    return min(miembros, key=lambda r: (not r.get("lei_firme"), PRIORIDAD_ANCLA[r["fuente"]], r["clave"]))["clave"]


def entity_ids(grupos: dict[str, list[dict]], previos: dict[str, str]) -> dict[str, str]:
    """entity_id estable por cluster (raíz -> entity_id).

    Si los miembros ya tenían un entity_id (corrida anterior), el cluster lo conserva: el que más
    miembros tenía (empate: el menor). Si dos clusters reclaman el mismo, lo conserva el que tiene más
    miembros que lo tenían (una división); los demás reciben uno nuevo. Un id nuevo es el hash del
    ancla, así que reprocesar desde cero da los mismos ids mientras el ancla no cambie.
    """
    reclamos: dict[str, list[tuple[int, str]]] = {}
    for raiz_, miembros in grupos.items():
        cuenta: dict[str, int] = {}
        for r in miembros:
            if r["clave"] in previos:
                cuenta[previos[r["clave"]]] = cuenta.get(previos[r["clave"]], 0) + 1
        if cuenta:
            eid = min(cuenta, key=lambda e: (-cuenta[e], e))
            reclamos.setdefault(eid, []).append((cuenta[eid], raiz_))
    asignado = {}
    for eid, rs in reclamos.items():
        ganador = min(rs, key=lambda x: (-x[0], x[1]))[1]
        asignado[ganador] = eid
    usados = set(asignado.values()) | set(previos.values())
    for raiz_, miembros in sorted(grupos.items()):
        if raiz_ in asignado:
            continue
        base = "E" + hashlib.sha1(ancla(miembros).encode()).hexdigest()[:12].upper()
        eid, i = base, 1
        while eid in usados:
            i += 1
            eid = f"{base}-{i}"
        asignado[raiz_] = eid
        usados.add(eid)
    return asignado


# ------------------------------------------------------------------ golden record

# Supervivencia por atributo: el primer registro del cluster que tiene el dato, en este orden de
# fuentes. GLEIF es el registro oficial de entidades legales; la SEC, el regulador de los emisores;
# Wikidata es colaborativa; OpenSanctions y GDELT agregan terceros.
SUPERVIVENCIA = {
    "nombre": ["gleif", "sec_edgar", "wikidata", "opensanctions", "gdelt"],
    "pais": ["gleif", "sec_edgar", "wikidata", "opensanctions", "gdelt"],
    "ciudad": ["gleif", "sec_edgar"],
    "lei": ["gleif", "opensanctions"],
    "cik": ["sec_edgar", "gdelt"],         # Wikidata no: sus identificadores son señal (D11)
    "ticker": ["sec_edgar", "wikidata"],
    "sitio_web": ["sec_edgar", "wikidata"],
    "forma_juridica": ["gleif", "sec_edgar"],
    "estado_entidad": ["gleif"],
    "estado_registro": ["gleif"],
}


def _valor(r: dict, atributo: str):
    if atributo == "nombre":
        return r["nombres"][0] if r["nombres"] else None
    if atributo == "pais":
        return r["paises"][0] if r["paises"] else None
    if atributo == "lei":
        firmes = sorted(leis_firmes(r))
        return firmes[0] if firmes else None
    if atributo == "cik":
        return sorted(r["ciks"])[0] if r["ciks"] else None
    if atributo == "ticker":
        return sorted(r["tickers"])[0] if r["tickers"] else None
    if atributo == "ciudad":
        return r.get("ciudad")
    return (r.get("datos") or {}).get(atributo)


def golden(entity_id: str, miembros: list[dict]) -> dict:
    """Una fila por entidad, con la fuente de cada atributo que sobrevive."""
    def clave_orden(fuentes):
        # Dentro de GLEIF, el registro firme primero (el duplicado anulado nunca gana).
        return lambda r: (fuentes.index(r["fuente"]), not r.get("lei_firme"), r["clave"])

    g = {"entity_id": entity_id, "registro_ancla": ancla(miembros)}
    procedencia = {}
    for atributo, fuentes in SUPERVIVENCIA.items():
        g[atributo] = None
        for r in sorted((m for m in miembros if m["fuente"] in fuentes), key=clave_orden(fuentes)):
            v = _valor(r, atributo)
            if v not in (None, ""):
                g[atributo], procedencia[atributo] = v, r["clave"]
                break
    os_ = [m for m in miembros if m["fuente"] == "opensanctions"]
    g["sancionada"] = any((m.get("datos") or {}).get("sancionada") for m in os_)
    g["en_listas_de_riesgo"] = bool(os_)
    g["fuentes"] = sorted({m["fuente"] for m in miembros})
    g["registros"] = len(miembros)
    g["duplicados_en_gleif"] = max(0, sum(m["fuente"] == "gleif" for m in miembros) - 1)
    g["procedencia"] = procedencia
    return g
