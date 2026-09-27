"""Set de validación curado a mano (D11), parte B: etiquetas por par (precisión en los casos difíciles).

Lee los pares que puntuó la primera corrida de la resolución (resolution.par_candidato, pesos sin
calibrar) y arma ~60 pares para que un humano decida si son la misma entidad legal.

Qué pares entran:
- **No** los de un registro de la parte A contra GLEIF: la respuesta de la parte A ya los decide
  (su LEI, `ninguno` u `otro`), y la parte A da la precisión y el recall de esos registros. Tampoco
  los de un registro ligado a uno de la parte A por un CIK o un LEI compartido (una clave de GDELT
  con el CIK de un emisor de la SEC): es la misma entidad, así que la parte A también los decide.
- **No** los vetados (dos LEI firmes o dos CIK distintos): la restricción ya decide.
- Sí todo lo demás: duplicados dentro de GLEIF (LEI anulado contra vigente) y pares entre fuentes
  sin LEI (SEC, OpenSanctions, Wikidata, GDELT), que la parte A no cubre.

Estratos (del lado del modelo, antes de la etiqueta):
- `dudoso`: decisión `revisar` o conflicto de la restricción. Entran todos (tope DUDOSOS_MAX).
- `positivo_dificil`: unido (aceptado o determinístico) con similitud de nombre < 90.
- `negativo_dificil`: rechazado con similitud de nombre >= 85.
- `facil`: aceptado o determinístico con similitud >= 95.
Los estratos se completan hasta OBJETIVO con muestreo de semilla fija.

El CSV **no lleva puntaje ni estrato**, y los pares van en orden aleatorio, para no anclar al que
etiqueta. El estrato queda en `parte_b_estratos.csv`, que se usa para la partición de calibración:
no abrirlo antes de terminar de etiquetar.

Uso (desde la raíz del repo, después de la corrida del job con la tarea `resolucion`):
    .venv\\Scripts\\python.exe databricks\\resolucion\\validacion\\generar_parte_b.py
El script **pisa** `parte_b.csv`: no regenerarlo después de empezar a etiquetar.
"""

import csv
import random
import sys
from pathlib import Path
from urllib.parse import quote

from databricks.sdk import WorkspaceClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_parte_a import PERFIL, WAREHOUSE, consultar  # noqa: E402

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "parte_b.csv"
ESTRATOS = AQUI / "parte_b_estratos.csv"
PARTE_A = AQUI / "parte_a.csv"
R = "entity360.resolution"
OBJETIVO = 60
DUDOSOS_MAX = 30
SEMILLA = 20260927


def claves_parte_a() -> set[str]:
    with PARTE_A.open(encoding="utf-8-sig", newline="") as f:
        return {f"{r['fuente']}:{r['id_fuente']}" for r in csv.DictReader(f, delimiter=";")}


def ligados_a(en_a: set[str], deterministicos: list[tuple[str, str]]) -> set[str]:
    """Registros de la parte A más los que no son de GLEIF y comparten CIK o LEI con alguno de ellos
    (clausura transitiva). GLEIF no propaga: sus pares con los de A son justamente lo que A decide."""
    ligados, cambio = set(en_a), True
    while cambio:
        cambio = False
        for x, y in deterministicos:
            for a, b in ((x, y), (y, x)):
                if a in ligados and b not in ligados and not b.startswith("gleif:"):
                    ligados.add(b)
                    cambio = True
    return ligados


def link(clave: str) -> str:
    fuente, id_ = clave.split(":", 1)
    return {
        "gleif": f"https://search.gleif.org/#/record/{id_}",
        "sec_edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={id_}",
        "opensanctions": f"https://www.opensanctions.org/entities/{id_}/",
        "wikidata": f"https://www.wikidata.org/wiki/{id_}",
        "gdelt": "producers/gcp_gdelt/alias.json",
    }[fuente]


def estrato(p: dict, en_revision: set) -> str | None:
    sim = p["similitud_nombre"]
    if (p["clave_a"], p["clave_b"]) in en_revision or p["decision"] == "revisar":
        return "dudoso"
    if p["decision"] in ("aceptado", "determinístico"):
        if sim is not None and sim < 90:
            return "positivo_dificil"
        if sim is not None and sim >= 95:
            return "facil"
    if p["decision"] == "rechazado" and sim is not None and sim >= 85:
        return "negativo_dificil"
    return None


def main() -> int:
    w = WorkspaceClient(profile=PERFIL)
    wh = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    q = lambda sql: consultar(w, wh, sql)  # noqa: E731

    en_a = claves_parte_a()
    registros = {r["clave"]: r for r in q(f"SELECT * FROM {R}.registro")}
    en_revision = {(r["clave_a"], r["clave_b"]) for r in q(f"SELECT clave_a, clave_b FROM {R}.revision")}
    pares = q(f"""SELECT clave_a, clave_b, decision, CAST(similitud_nombre AS DOUBLE) AS similitud_nombre
                  FROM {R}.par_candidato WHERE decision <> 'veto'""")
    for p in pares:
        p["similitud_nombre"] = float(p["similitud_nombre"]) if p["similitud_nombre"] is not None else None
    en_a = ligados_a(en_a, [(p["clave_a"], p["clave_b"]) for p in pares if p["decision"] == "determinístico"])

    def cubierto_por_a(p):
        a, b = p["clave_a"], p["clave_b"]
        return (a in en_a and b.startswith("gleif:")) or (b in en_a and a.startswith("gleif:"))

    por_estrato: dict[str, list[dict]] = {}
    for p in pares:
        if cubierto_por_a(p):
            continue
        e = estrato(p, en_revision)
        if e:
            por_estrato.setdefault(e, []).append(p)

    rnd = random.Random(SEMILLA)
    elegidos = []
    dudosos = sorted(por_estrato.get("dudoso", []), key=lambda p: (p["clave_a"], p["clave_b"]))
    rnd.shuffle(dudosos)
    elegidos += [(p, "dudoso") for p in dudosos[:DUDOSOS_MAX]]
    otros = ["positivo_dificil", "negativo_dificil", "facil"]
    cupo = max(0, OBJETIVO - len(elegidos))
    for i, e in enumerate(otros):
        lista = sorted(por_estrato.get(e, []), key=lambda p: (p["clave_a"], p["clave_b"]))
        rnd.shuffle(lista)
        n = cupo // (len(otros) - i)
        tomados = lista[:n]
        elegidos += [(p, e) for p in tomados]
        cupo -= len(tomados)
    rnd.shuffle(elegidos)

    def lado(clave: str, prefijo: str) -> dict:
        r = registros[clave]
        ids = [f"LEI {','.join(r['leis'])}" if r["leis"] else "", f"CIK {','.join(map(str, r['ciks']))}" if r["ciks"] else "",
               f"ticker {','.join(r['tickers'])}" if r["tickers"] else "", f"web {','.join(r['dominios'])}" if r["dominios"] else ""]
        return {f"{prefijo}_fuente": r["fuente"], f"{prefijo}_id": r["id_fuente"], f"{prefijo}_nombre": r["nombre"],
                f"{prefijo}_otros_nombres": " | ".join([n for n in r["nombres"] if n != r["nombre"]][:6]),
                f"{prefijo}_pais": ",".join(r["paises"]), f"{prefijo}_ciudad": r["ciudad"] or "",
                f"{prefijo}_identificadores": "; ".join(x for x in ids if x), f"{prefijo}_link": link(clave)}

    filas, estratos = [], []
    for n, (p, e) in enumerate(elegidos, 1):
        pid = f"B{n:03d}"
        a, b = (p["clave_a"], p["clave_b"]) if rnd.random() < 0.5 else (p["clave_b"], p["clave_a"])
        filas.append({"par_id": pid, **lado(a, "a"), **lado(b, "b"),
                      "buscar_en_gleif": f"https://search.gleif.org/#/search/simpleSearch={quote(registros[a]['nombre'] or '')}",
                      "respuesta": "", "evidencia": "", "fecha": ""})
        estratos.append({"par_id": pid, "estrato": e, "clave_a": a, "clave_b": b})

    campos = ["par_id"] + [f"{s}_{c}" for s in ("a", "b") for c in
                           ("fuente", "id", "nombre", "otros_nombres", "pais", "ciudad", "identificadores", "link")]
    campos += ["buscar_en_gleif", "respuesta", "evidencia", "fecha"]
    # ";" y UTF-8 con BOM: Excel en castellano lo abre en columnas y con acentos.
    with SALIDA.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        wr.writeheader()
        wr.writerows(filas)
    with ESTRATOS.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["par_id", "estrato", "clave_a", "clave_b"], delimiter=";")
        wr.writeheader()
        wr.writerows(estratos)
    # Solo conteos: ni puntajes ni pares en la salida.
    disponibles = {e: len(v) for e, v in sorted(por_estrato.items())}
    tomados = {}
    for _, e in elegidos:
        tomados[e] = tomados.get(e, 0) + 1
    print(f"{SALIDA.name}: {len(filas)} pares {dict(sorted(tomados.items()))} (disponibles {disponibles})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
