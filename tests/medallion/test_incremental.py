"""Silver incremental (2026-09-29): procesar de a lotes da lo mismo que el recálculo completo.

El recálculo completo es lo que hacía Silver antes: tomar todo Bronze y quedarse con la última
extracción por clave (row_number, orden descendente con nulos al final, desempate por ingesta). El
incremental aplica cada lote nuevo sobre lo que Silver ya tiene con incremental.gana y reemplaza las
tablas hijas de los padres que ganaron con incremental.delta_hijos.
"""

import itertools
import json
import random
from pathlib import Path

import incremental as I
import scd2

DATOS = Path(__file__).parent / "datos"
CLAVES_CDC = {"entidad": ("lei",), "direccion": ("lei", "tipo"), "nombre_alternativo": ("lei", "orden"),
              "relacion": ("lei_hijo", "lei_padre", "tipo")}


# ------------------------------------------------------------------ capa 3: última extracción

def completo(lotes: list[list[dict]]) -> dict:
    """Todo Bronze de una vez, como antes: por clave, mayor orden (nulos al final) y, a igual orden, el
    último ingerido (índice de lote más alto)."""
    filas = [(i, r) for i, lote in enumerate(lotes) for r in lote]
    mejor = {}
    for i, r in filas:
        k = r["clave"]
        rango = (r["orden"] is not None, r["orden"] if r["orden"] is not None else "", i)
        if k not in mejor or rango > mejor[k][0]:
            mejor[k] = (rango, r)
    return {k: v[1] for k, v in mejor.items()}


def incremental(lotes: list[list[dict]]) -> tuple[dict, dict]:
    """Un lote por corrida: dentro del lote, la última por clave; después MERGE si gana. Devuelve
    (Silver, hijos) donde hijos = clave -> conjunto de nombres."""
    silver, hijos = {}, {}
    for lote in lotes:
        del_lote = completo([lote])
        for k, r in del_lote.items():
            actual = silver.get(k)
            if I.gana(r["orden"], actual["orden"] if actual else None):
                silver[k] = r
                upsert, borrar = I.delta_hijos(set(r["nombres"]), hijos.get(k, set()))
                hijos[k] = (hijos.get(k, set()) - borrar) | upsert
    return silver, hijos


def lotes_al_azar(semilla: int) -> list[list[dict]]:
    rnd = random.Random(semilla)
    lotes = []
    for _ in range(rnd.randint(1, 6)):
        lote = []
        for _ in range(rnd.randint(0, 8)):
            orden = rnd.choice([None, "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28"])
            lote.append({"clave": rnd.choice("ABCDE"), "orden": orden, "valor": rnd.random(),
                         "nombres": tuple(sorted(rnd.sample(["x", "y", "z", "w"], rnd.randint(1, 3))))})
        lotes.append(lote)
    return lotes


def test_capa3_incremental_igual_al_completo():
    for semilla in range(500):
        lotes = lotes_al_azar(semilla)
        silver, hijos = incremental(lotes)
        esperado = completo(lotes)
        assert silver == esperado, semilla
        assert hijos == {k: set(r["nombres"]) for k, r in esperado.items()}, semilla


def test_gana_nulos_al_final_y_empate_para_el_nuevo():
    assert I.gana("2026-09-27", None) and I.gana(None, None) and I.gana("2026-09-27", "2026-09-27")
    assert not I.gana(None, "2026-09-27") and not I.gana("2026-09-26", "2026-09-27")


def test_lote_viejo_reprocesado_no_pisa():
    """OpenSanctions: un snapshot anterior (último cambio más viejo) que se reprocesa no vuelve atrás."""
    nuevo = [{"clave": "NK-1", "orden": "2026-09-27", "valor": 2, "nombres": ("ACME SA",)}]
    viejo = [{"clave": "NK-1", "orden": "2026-09-20", "valor": 1, "nombres": ("ACME", "ACME SA")}]
    silver, hijos = incremental([nuevo, viejo])
    assert silver["NK-1"]["valor"] == 2 and hijos["NK-1"] == {"ACME SA"}


def test_hijos_se_reemplazan_solo_para_padres_que_ganaron():
    """Un alias que OpenSanctions sacó en el último snapshot desaparece; los demás padres no se tocan."""
    l1 = [{"clave": "A", "orden": "1", "valor": 0, "nombres": ("a1", "a2")},
          {"clave": "B", "orden": "1", "valor": 0, "nombres": ("b1",)}]
    l2 = [{"clave": "A", "orden": "2", "valor": 0, "nombres": ("a1",)}]
    _, hijos = incremental([l1, l2])
    assert hijos == {"A": {"a1"}, "B": {"b1"}}


def test_pendientes():
    assert I.pendientes({"s1", "s2", "s3"}, {"s1"}) == {"s2", "s3"}
    assert I.pendientes({"s1"}, set()) == {"s1"}         # tabla vacía: reproceso completo
    assert I.pendientes({"s1"}, {"s1"}) == set()          # sin lotes nuevos: la fuente se saltea


# ------------------------------------------------------------------ SCD2: los cambios reales del CDC

def leer(nombre):
    return [json.loads(l) for l in (DATOS / nombre).read_text(encoding="utf-8").splitlines() if l]


def aplicar_scd2(hist: dict, cambios: list[dict]):
    por_clave = {}
    for c in cambios:
        por_clave.setdefault((c["tabla"],) + tuple(c["datos"][k] for k in CLAVES_CDC[c["tabla"]]), []).append(c)
    for k, cs in por_clave.items():
        versiones = hist.setdefault(k, [])
        cierre, nuevas = scd2.aplicar(cs, versiones[-1] if versiones else None)
        if cierre:
            versiones[-1]["valido_hasta"] = cierre
        versiones += nuevas


def test_scd2_por_lotes_igual_que_todo_junto():
    """Los dos lotes reales del CDC (2026-09-25 y 2026-09-26), en cualquier partición en lotes y aunque
    un lote se reprocese, dan las mismas versiones que aplicar todo de una vez."""
    cambios = leer("cdc_2026-09-25_mismas_claves.jsonl") + leer("cdc_2026-09-26.jsonl")
    todo = {}
    aplicar_scd2(todo, cambios)
    ordenados = sorted(cambios, key=lambda c: (c["lsn"], c["seqval"]))
    for cortes in itertools.combinations(range(1, len(ordenados)), 2):
        lotes = [ordenados[:cortes[0]], ordenados[cortes[0]:cortes[1]], ordenados[cortes[1]:]]
        hist = {}
        for lote in lotes + [lotes[0]]:                  # el primer lote se reprocesa al final
            aplicar_scd2(hist, lote)
        assert hist == todo, cortes
