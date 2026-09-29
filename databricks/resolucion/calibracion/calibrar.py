"""Calibración de pesos y umbrales de la resolución de identidades contra el set curado (D11, regla 08).

1. Reconstruye la resolución en local con el mismo código del job (databricks/medallion/identidades.py)
   sobre resolution.registro: blocking, señales de cada par, clusters.
2. Parte el set de validación (A + B) en calibración y evaluación: por estrato (A: fuente; B: el
   estrato de parte_b_estratos.csv), semilla fija, mitad y mitad.
3. Busca en una grilla los pesos y el umbral de aceptación que maximizan F1 sobre la mitad de
   calibración (desempate: más precisión; después, lo más cerca de los pesos iniciales).
4. Informa sobre la mitad de **evaluación**, con los pesos iniciales y con los calibrados: precisión,
   recall y recall del blocking, con intervalo de Wilson al 95 %.

Unidades (se suman A y B):
- Parte A, por registro: predicho positivo si su cluster tiene algún registro de GLEIF; verdadero
  positivo si ese cluster tiene el LEI de la etiqueta. Un registro unido al LEI equivocado cuenta como
  falso positivo y como falso negativo. `incierto` queda afuera.
- Parte B, por par: predicho match si los dos registros quedan en el mismo cluster.
- Recall del blocking (solo A: los pares de B salieron del blocking): el par (registro, LEI de la
  etiqueta) es candidato directo, o está conectado en el grafo de candidatos no vetados.

No cambia el job: escribe resultados_<version>.json; aplicar los pesos es un paso aparte. Las señales y
el puntaje son identidades.senales / identidades.decidir: el mismo código que corre el job.

Versiones: v1 = resolución inicial (commit 51ee671, medición ciega); v2 = con las correcciones de la
calibración (sin país supuesto en GDELT, alias genéricos, gemelo de LEI y empates a revisión,
identificadores de Wikidata como señal); v2.1 = v2 + token único raro por idf y país heredado en GDELT.
La mitad de evaluación no es ciega para la v2 ni para la v2.1: sus errores se miraron para diagnosticar.

Uso (desde la raíz del repo, después de correr la tarea `resolucion` con el código de la versión):
    .venv\\Scripts\\python.exe databricks\\resolucion\\calibracion\\calibrar.py --version v2
"""

import argparse
import csv
import itertools
import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "databricks" / "medallion"))
sys.path.insert(0, str(RAIZ / "databricks" / "resolucion" / "validacion"))
import identidades as I  # noqa: E402
import metricas  # noqa: E402
from generar_parte_a import PERFIL, WAREHOUSE, consultar  # noqa: E402

VALIDACION = RAIZ / "databricks" / "resolucion" / "validacion"
AQUI = Path(__file__).resolve().parent
SEMILLA = 20260927

INICIALES = {**I.PESOS, "nombre_piso": I.NOMBRE_PISO, "umbral_aceptar": I.UMBRAL_ACEPTAR}
GRILLA = {
    "nombre": [40, 50, 60, 70],
    "nombre_piso": [60, 70, 80],
    "pais_igual": [0, 10, 20],
    "pais_distinto": [-10, -20, -40],
    "id_debil": [20, 30, 40],           # ticker y dominio, el mismo peso
    "fondo_vs_no_fondo": [-20, -30, -50],
    "numeros_distintos": [-10, -20, -40],
    "umbral_aceptar": [60, 65, 70, 75, 80],
}


# ------------------------------------------------------------------ resolución local

def registros_de_silver() -> list[dict]:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient(profile=PERFIL)
    wh = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    filas = consultar(w, wh, "SELECT * FROM entity360.resolution.registro")
    return [{"clave": f["clave"], "fuente": f["fuente"], "id_fuente": f["id_fuente"], "nombres": f["nombres"],
             "paises": f["paises"], "ciudad": f["ciudad"], "leis": f["leis"],
             "lei_firme": f["lei_firme"] in (True, "true"), "ciks": [int(c) for c in f["ciks"]],
             "tickers": f["tickers"], "dominios": f["dominios"], "datos": {}} for f in filas]


def pesos_de(p: dict) -> dict:
    """Pesos de la grilla -> diccionario de identidades.PESOS (ticker y dominio comparten peso)."""
    return {**I.PESOS, **{k: p[k] for k in ("nombre", "pais_igual", "pais_distinto", "fondo_vs_no_fondo",
                                             "numeros_distintos")}, "ticker": p["id_debil"], "dominio": p["id_debil"]}


def resolver(regs, pares, sen, p) -> dict[str, str]:
    """Decisiones con identidades.decidir (el mismo código del job) y clusters con identidades.clusters."""
    pesos = pesos_de(p)
    lista = []
    for (a, b) in pares:
        d = I.decidir(sen[(a, b)], pesos, p["nombre_piso"], p["umbral_aceptar"])
        lista.append({"clave_a": a, "clave_b": b, "decision": d["decision"], "puntaje": d["puntaje"]})
    raices, _ = I.clusters(regs, lista)
    return raices


# ------------------------------------------------------------------ set de validación

def unidades() -> list[dict]:
    out = []
    with (VALIDACION / "parte_a.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            resp = r["respuesta"].strip()
            if resp == "incierto":
                continue
            lei = r[f"c{resp}_lei"] if resp in "12345" and len(resp) == 1 else (r["lei_otro"].strip() if resp == "otro" else None)
            out.append({"id": r["registro_id"], "parte": "A", "estrato": r["fuente"],
                        "clave": f"{r['fuente']}:{r['id_fuente']}", "lei": lei or None})
    estratos = {}
    with (VALIDACION / "parte_b_estratos.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            estratos[r["par_id"]] = r
    with (VALIDACION / "parte_b.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["respuesta"] == "incierto":
                continue
            e = estratos[r["par_id"]]
            out.append({"id": r["par_id"], "parte": "B", "estrato": e["estrato"], "clave_a": e["clave_a"],
                        "clave_b": e["clave_b"], "match": r["respuesta"] == "match"})
    return out


def partir(us: list[dict]) -> tuple[list[dict], list[dict]]:
    """Mitad y mitad dentro de cada estrato (parte + estrato), semilla fija."""
    rnd = random.Random(SEMILLA)
    cal, ev = [], []
    grupos: dict[tuple, list[dict]] = {}
    for u in us:
        grupos.setdefault((u["parte"], u["estrato"]), []).append(u)
    for k in sorted(grupos):
        g = sorted(grupos[k], key=lambda u: u["id"])
        rnd.shuffle(g)
        mitad = (len(g) + 1) // 2
        cal += g[:mitad]
        ev += g[mitad:]
    return cal, ev


def contar(us: list[dict], raices: dict[str, str], gleif_por_raiz: dict[str, set]) -> dict:
    vp = fp = fn = 0
    for u in us:
        if u["parte"] == "A":
            leis = gleif_por_raiz.get(raices[u["clave"]], set())
            acierto = u["lei"] is not None and f"gleif:{u['lei']}" in leis
            vp += acierto
            fp += bool(leis) and not acierto
            fn += u["lei"] is not None and not acierto
        else:
            junto = raices[u["clave_a"]] == raices[u["clave_b"]]
            vp += junto and u["match"]
            fp += junto and not u["match"]
            fn += (not junto) and u["match"]
    return {"vp": vp, "fp": fp, "fn": fn}


def medir(c: dict) -> dict:
    p_n, r_n = c["vp"] + c["fp"], c["vp"] + c["fn"]
    prec = c["vp"] / p_n if p_n else None
    rec = c["vp"] / r_n if r_n else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
    return {**c, "precision": prec, "precision_ic95": metricas.wilson(c["vp"], p_n),
            "recall": rec, "recall_ic95": metricas.wilson(c["vp"], r_n), "f1": f1}


def blocking(us: list[dict], pares: set, sen: dict) -> dict:
    """Recall del blocking en la parte A: par directo y conexión por candidatos no vetados."""
    vecinos: dict[str, set] = {}
    for (a, b) in pares:
        if not sen[(a, b)]["veto"]:
            vecinos.setdefault(a, set()).add(b)
            vecinos.setdefault(b, set()).add(a)
    positivos = [u for u in us if u["parte"] == "A" and u["lei"]]
    directo = conectado = 0
    for u in positivos:
        destino = f"gleif:{u['lei']}"
        directo += tuple(sorted((u["clave"], destino))) in pares
        vistos, pila = {u["clave"]}, [u["clave"]]
        while pila:
            for v in vecinos.get(pila.pop(), ()):
                if v not in vistos:
                    vistos.add(v)
                    pila.append(v)
        conectado += destino in vistos
    n = len(positivos)
    return {"n": n, "directo": directo, "directo_ic95": metricas.wilson(directo, n),
            "conectado": conectado, "conectado_ic95": metricas.wilson(conectado, n)}


def errores(us: list[dict], raices: dict[str, str], regs: list[dict]) -> list[str]:
    """Unidades con algún falso positivo o falso negativo."""
    gleif: dict[str, set] = {}
    for r in regs:
        if r["fuente"] == "gleif":
            gleif.setdefault(raices[r["clave"]], set()).add(r["clave"])
    return [u["id"] for u in us if (lambda c: c["fp"] or c["fn"])(contar([u], raices, gleif))]


def evaluar(regs, pares, sen, p, us):
    raices = resolver(regs, pares, sen, p)
    gleif: dict[str, set] = {}
    for r in regs:
        if r["fuente"] == "gleif":
            gleif.setdefault(raices[r["clave"]], set()).add(r["clave"])
    return medir(contar(us, raices, gleif)), raices


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v2")
    version = ap.parse_args().version
    regs = I.preparar(registros_de_silver())
    pares_bl, resumen = I.pares_candidatos(regs)
    pares = set(pares_bl) | I.pares_por_identificador(regs)
    por_clave = {r["clave"]: r for r in regs}
    sen = {(a, b): I.senales(por_clave[a], por_clave[b]) for (a, b) in pares}
    ini = {k: INICIALES[k] for k in ("nombre", "nombre_piso", "pais_igual", "pais_distinto", "fondo_vs_no_fondo",
                                     "numeros_distintos", "umbral_aceptar")} | {"id_debil": I.PESOS["ticker"]}
    _, raices_ini = evaluar(regs, pares, sen, ini, [])
    print(f"reconstrucción local: {len(regs)} registros, {len(pares)} pares, "
          f"{len(set(raices_ini.values()))} entidades con los pesos iniciales")

    us = unidades()
    cal, ev = partir(us)
    print(f"set: {len(us)} unidades (A {sum(u['parte'] == 'A' for u in us)}, B {sum(u['parte'] == 'B' for u in us)}); "
          f"calibración {len(cal)}, evaluación {len(ev)}")

    mejor, clave_mejor = None, None
    claves = list(GRILLA)
    for combo in itertools.product(*GRILLA.values()):
        p = dict(zip(claves, combo))
        m, _ = evaluar(regs, pares, sen, p, cal)
        distancia = sum(abs(p[k] - ini[k]) for k in claves)
        orden = (m["f1"], m["precision"] or 0, -distancia)
        if clave_mejor is None or orden > clave_mejor:
            mejor, clave_mejor = (p, m), orden
    p_cal, m_cal = mejor

    res = {"version": version, "entidades_con_iniciales": len(set(raices_ini.values())), "semilla": SEMILLA, "unidades": {"calibracion": len(cal), "evaluacion": len(ev)},
           "pesos_iniciales": ini, "pesos_calibrados": p_cal, "calibracion_con_calibrados": m_cal,
           "calibracion_con_iniciales": evaluar(regs, pares, sen, ini, cal)[0],
           "evaluacion_con_iniciales": evaluar(regs, pares, sen, ini, ev)[0],
           "evaluacion_con_calibrados": evaluar(regs, pares, sen, p_cal, ev)[0],
           "evaluacion_por_parte": {parte: {"iniciales": evaluar(regs, pares, sen, ini, [u for u in ev if u["parte"] == parte])[0],
                                            "calibrados": evaluar(regs, pares, sen, p_cal, [u for u in ev if u["parte"] == parte])[0]}
                                    for parte in "AB"},
           "errores_con_iniciales": errores(us, raices_ini, regs),
           "blocking_evaluacion": blocking(ev, pares, sen), "blocking_todo_a": blocking(us, pares, sen),
           "resumen_blocking": resumen}
    (AQUI / f"resultados_{version}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=list) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
