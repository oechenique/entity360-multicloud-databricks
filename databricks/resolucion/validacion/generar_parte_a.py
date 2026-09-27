"""Set de validación curado a mano (D11), parte A: etiquetas por registro (dan el recall).

Para cada registro que necesita matching difuso (no comparte LEI con GLEIF), hasta 5 candidatos del
legacy (GLEIF) para que un humano elija cuál es su LEI, o ninguno. Los candidatos salen de una
búsqueda amplia (todos los nombres de GLEIF, sin filtro de país ni blocking), para que la parte A
también mida el recall del blocking. El orden de los candidatos es aleatorio (semilla fija por
registro) y el CSV **no lleva el score**, para no anclar al que etiqueta.

Registros:
- SEC EDGAR: los 16 emisores (ninguno trae LEI).
- OpenSanctions: los del universo sin LEI (país AR).
- Wikidata: los ítems sin LEI.
- GDELT: las claves de alias.json sin CIK (BANCO_GALICIA).

Lee Silver por el SQL warehouse con el perfil de la CLI (nada de credenciales en el código).
Uso (desde la raíz del repo):
    .venv\\Scripts\\python.exe databricks\\resolucion\\validacion\\generar_parte_a.py
"""

import csv
import json
import random
import sys
from pathlib import Path
from urllib.parse import quote

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState
from rapidfuzz import fuzz

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "databricks" / "medallion"))
import normalizacion as N  # noqa: E402

PERFIL = "entity360-free"
WAREHOUSE = "Serverless Starter Warehouse"
SALIDA = Path(__file__).resolve().parent / "parte_a.csv"
CANDIDATOS = 5
S = "entity360.silver"


def consultar(w: WorkspaceClient, wh: str, sql: str) -> list[dict]:
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=wh, wait_timeout="50s",
                                                format=Format.JSON_ARRAY, disposition=Disposition.INLINE)
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}")
    cols = [c.name for c in r.manifest.schema.columns]
    filas = [dict(zip(cols, f)) for f in (r.result.data_array or [])]
    for c in r.manifest.schema.columns:          # arrays y structs llegan como texto JSON
        if c.type_name.value in ("ARRAY", "STRUCT", "MAP"):
            for f in filas:
                f[c.name] = json.loads(f[c.name]) if f[c.name] else []
    return filas


def variantes(nombres: list[str]) -> list[tuple[str, str]]:
    """(tokens canónicos, nombre sin forma jurídica) de cada nombre no vacío."""
    out = []
    for n in nombres:
        x = N.nombre(n)
        if x["sin_forma"]:
            out.append((" ".join(sorted(x["tokens"])), x["sin_forma"]))
    return out


def similitud(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> float:
    return max((max(fuzz.token_set_ratio(ta, tb), fuzz.ratio(sa, sb)) for ta, sa in a for tb, sb in b), default=0.0)


def main() -> int:
    w = WorkspaceClient(profile=PERFIL)
    wh = next(x.id for x in w.warehouses.list() if x.name == WAREHOUSE)
    q = lambda sql: consultar(w, wh, sql)  # noqa: E731

    gleif = q(f"""
        SELECT e.lei, e.nombre_legal, e.jurisdiccion, e.estado_registro, e.estado_entidad, e.alcance,
               d.ciudad AS ciudad_sede,
               collect_list(n.nombre) AS alternativos
        FROM {S}.gleif_entidad e
        JOIN {S}.gleif_lei l USING (lei)
        LEFT JOIN {S}.gleif_direccion d ON d.lei = e.lei AND d.tipo = 'SEDE'
        LEFT JOIN {S}.gleif_nombre_alternativo n ON n.lei = e.lei
        WHERE l.lei_valido
        GROUP BY ALL""")
    for g in gleif:
        g["_var"] = variantes([g["nombre_legal"], *g["alternativos"]])

    registros = []
    for r in q(f"""SELECT e.cik, e.nombre, e.ticker, e.pais_incorporacion, e.pais_sede, e.ciudad_sede,
                          collect_list(CASE WHEN n.tipo = 'anterior' THEN n.nombre END) AS anteriores
                   FROM {S}.sec_emisor e LEFT JOIN {S}.sec_nombre n USING (cik) GROUP BY ALL ORDER BY e.cik"""):
        registros.append({"fuente": "sec_edgar", "id_fuente": str(r["cik"]), "nombre": r["nombre"],
                          "otros_nombres": r["anteriores"], "pais": r["pais_incorporacion"] or r["pais_sede"],
                          "ciudad": r["ciudad_sede"], "extra": f"ticker {r['ticker']}",
                          "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={r['cik']}"})
    for r in q(f"""SELECT id, nombre, aliases, paises, esquema, sancionada, direcciones
                   FROM {S}.opensanctions_entidad WHERE en_universo AND size(leis) = 0 ORDER BY id"""):
        registros.append({"fuente": "opensanctions", "id_fuente": r["id"], "nombre": r["nombre"],
                          "otros_nombres": r["aliases"], "pais": ",".join(r["paises"]), "ciudad": None,
                          "extra": f"{r['esquema']}; sancionada={str(r['sancionada']).lower()}; "
                                   f"direcciones: {(r['direcciones'] or '')[:150]}",
                          "link": f"https://www.opensanctions.org/entities/{r['id']}/"})
    for r in q(f"""SELECT qid, etiqueta_es, etiqueta_en, ciks, simbolos, paises, dominios
                   FROM {S}.wikidata_item WHERE size(leis) = 0 ORDER BY qid"""):
        registros.append({"fuente": "wikidata", "id_fuente": r["qid"], "nombre": r["etiqueta_es"] or r["etiqueta_en"],
                          "otros_nombres": [x for x in (r["etiqueta_en"],) if x and x != r["etiqueta_es"]],
                          "pais": ",".join(r["paises"]), "ciudad": None,
                          "extra": f"CIK {','.join(map(str, r['ciks'])) or '-'}; ticker {','.join(r['simbolos']) or '-'}; "
                                   f"web {','.join(r['dominios']) or '-'}",
                          "link": f"https://www.wikidata.org/wiki/{r['qid']}"})
    alias = json.loads((RAIZ / "producers" / "gcp_gdelt" / "alias.json").read_text(encoding="utf-8"))
    for e in alias["entidades"]:
        if e.get("cik") is None:
            registros.append({"fuente": "gdelt", "id_fuente": e["clave"], "nombre": e["nombre"],
                              "otros_nombres": [a["forma"] for a in e["alias"]], "pais": "AR", "ciudad": None,
                              "extra": "clave del diccionario de alias de GDELT (sin CIK)",
                              "link": "producers/gcp_gdelt/alias.json"})

    campos = ["registro_id", "fuente", "id_fuente", "nombre", "otros_nombres", "pais", "ciudad", "datos_extra", "link_fuente"]
    for i in range(1, CANDIDATOS + 1):
        campos += [f"c{i}_lei", f"c{i}_nombre", f"c{i}_pais", f"c{i}_ciudad", f"c{i}_estado", f"c{i}_link"]
    campos += ["buscar_en_gleif", "respuesta", "lei_otro", "evidencia", "fecha"]

    filas = []
    for n, r in enumerate(registros, 1):
        rv = variantes([r["nombre"], *r["otros_nombres"]])
        mejores = sorted(gleif, key=lambda g: -similitud(rv, g["_var"]))[:CANDIDATOS]
        rid = f"A{n:03d}"
        random.Random(rid).shuffle(mejores)
        fila = {"registro_id": rid, "fuente": r["fuente"], "id_fuente": r["id_fuente"], "nombre": r["nombre"],
                "otros_nombres": " | ".join(r["otros_nombres"][:6]), "pais": r["pais"], "ciudad": r["ciudad"],
                "datos_extra": r["extra"], "link_fuente": r["link"],
                "buscar_en_gleif": f"https://search.gleif.org/#/search/simpleSearch={quote(r['nombre'])}",
                "respuesta": "", "lei_otro": "", "evidencia": "", "fecha": ""}
        for i, g in enumerate(mejores, 1):
            otros = [a for a in g["alternativos"] if a != g["nombre_legal"]]
            fila |= {f"c{i}_lei": g["lei"],
                     f"c{i}_nombre": g["nombre_legal"] + (f" (también: {' | '.join(otros[:3])})" if otros else ""),
                     f"c{i}_pais": N.pais(g["jurisdiccion"], "gleif"), f"c{i}_ciudad": g["ciudad_sede"],
                     f"c{i}_estado": f"{g['estado_entidad']}/{g['estado_registro']}",
                     f"c{i}_link": f"https://search.gleif.org/#/record/{g['lei']}"}
        filas.append(fila)

    # ";" y UTF-8 con BOM: Excel en castellano lo abre en columnas y con acentos.
    with SALIDA.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        wr.writeheader()
        wr.writerows(filas)
    por_fuente = {}
    for r in registros:
        por_fuente[r["fuente"]] = por_fuente.get(r["fuente"], 0) + 1
    print(f"{SALIDA.name}: {len(filas)} registros {por_fuente}, {CANDIDATOS} candidatos c/u")
    return 0


if __name__ == "__main__":
    sys.exit(main())
