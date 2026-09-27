"""SCD tipo 2 sobre el CDC del legacy (regla 08), para una clave a la vez.

Python puro: Silver lo corre con groupBy(clave).applyInPandas y los tests, locales.

Reglas (legacy/README.md y el extractor CDC):
- Orden por (lsn, seqval). Los LSN llegan en hexadecimal de ancho fijo: ordenar como texto es correcto.
- `update_antes` se descarta: la imagen `update` trae la fila completa.
- `insert` / `update` abren una versión nueva (valido_desde = commit_time) y cierran la anterior.
  Si los atributos no cambiaron (mismo hash, sin contar `modificado_en`), no abren versión.
- `delete` cierra la versión vigente sin abrir otra (solo pasa en nombre_alternativo).
- Cambios con LSN <= al último aplicado se ignoran: reprocesar un lote no duplica versiones.
"""

import hashlib
import json

TECNICAS = {"modificado_en"}   # columna del ERP que cambia en cada UPDATE aunque nada más cambie


def huella(datos: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in datos.items() if k not in TECNICAS},
                                     sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def aplicar(cambios: list[dict], ultima: dict | None) -> tuple[str | None, list[dict]]:
    """Aplica los cambios de UNA clave sobre su última versión en Silver.

    cambios: dicts con op, lsn, seqval, commit_time y datos (fila completa del ERP).
    ultima: la versión más reciente de la clave, abierta o cerrada ({_hash, _lsn, _seqval,
        valido_hasta, ...}), o None si la clave es nueva. Cerrada = la borró un delete.

    Devuelve (cierre, nuevas):
    - cierre: valido_hasta para `ultima` si estaba abierta y hay que cerrarla; si no, None.
    - nuevas: versiones a insertar, en orden; todas cerradas salvo, a lo sumo, la última.
    """
    ultimo = (ultima["_lsn"], ultima["_seqval"]) if ultima else ("", "")
    abierta_hash = ultima["_hash"] if ultima and ultima["valido_hasta"] is None else None
    cierre, nuevas = None, []

    def cerrar(ts):
        nonlocal cierre, abierta_hash
        if nuevas and nuevas[-1]["valido_hasta"] is None:
            nuevas[-1]["valido_hasta"] = ts
        elif abierta_hash is not None and cierre is None:
            cierre = ts
        abierta_hash = None

    for c in sorted(cambios, key=lambda c: (c["lsn"], c["seqval"])):
        if (c["lsn"], c["seqval"]) <= ultimo or c["op"] == "update_antes":
            continue
        if c["op"] == "delete":
            cerrar(c["commit_time"])
            continue
        if c["op"] not in ("insert", "update"):
            raise ValueError(f"operación desconocida: {c['op']}")
        h = huella(c["datos"])
        if h == abierta_hash:
            continue
        cerrar(c["commit_time"])
        nuevas.append({**c["datos"], "_hash": h, "_op": c["op"], "_lsn": c["lsn"], "_seqval": c["seqval"],
                       "valido_desde": c["commit_time"], "valido_hasta": None})
        abierta_hash = h
    return cierre, nuevas
