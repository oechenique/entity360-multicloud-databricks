"""SCD2 sobre el CDC del legacy (regla 08), con los cambios reales del 2026-09-25 y 2026-09-26.

datos/cdc_2026-09-26.jsonl: los 11 cambios del segundo lote (7 update, 4 insert).
datos/cdc_2026-09-25_mismas_claves.jsonl: los inserts del primer lote para esas mismas claves.
"""

import json
from collections import defaultdict
from pathlib import Path

import scd2

DATOS = Path(__file__).parent / "datos"
CLAVES = {"entidad": ("lei",), "direccion": ("lei", "tipo"), "nombre_alternativo": ("lei", "orden"),
          "relacion": ("lei_hijo", "lei_padre", "tipo")}


def leer(nombre):
    return [json.loads(l) for l in (DATOS / nombre).read_text(encoding="utf-8").splitlines() if l]


def clave(c):
    return (c["tabla"],) + tuple(c["datos"][k] for k in CLAVES[c["tabla"]])


class Silver:
    """Tabla _hist en memoria, aplicada como en Silver: por clave, con la última versión."""

    def __init__(self):
        self.hist = defaultdict(list)

    def aplicar(self, cambios):
        por_clave = defaultdict(list)
        for c in cambios:
            por_clave[clave(c)].append(c)
        for k, cs in por_clave.items():
            ultima = self.hist[k][-1] if self.hist[k] else None
            cierre, nuevas = scd2.aplicar(cs, ultima)
            if cierre:
                ultima["valido_hasta"] = cierre
            self.hist[k] += nuevas

    def vigentes(self):
        return {k: v[-1] for k, v in self.hist.items() if v and v[-1]["valido_hasta"] is None}

    def filas(self):
        return sum(len(v) for v in self.hist.values())


def cambio(op, lsn, datos, ts=None, tabla="nombre_alternativo"):
    return {"tabla": tabla, "op": op, "lsn": f"0x{lsn:020X}", "seqval": "0x00", "commit_time": ts or f"2026-09-27T00:00:{lsn:02d}",
            "datos": datos}


def test_cambios_reales():
    s = Silver()
    s.aplicar(leer("cdc_2026-09-25_mismas_claves.jsonl"))
    assert s.filas() == 7
    s.aplicar(leer("cdc_2026-09-26.jsonl"))
    # 7 updates con cambios reales abren 7 versiones; 4 inserts de claves nuevas abren 4
    assert s.filas() == 7 + 7 + 4
    assert len(s.vigentes()) == 11
    renombrada = [v for k, v in s.hist.items()
                  if k[0] == "entidad" and len(v) == 2 and v[0]["nombre_legal"] != v[1]["nombre_legal"]]
    assert len(renombrada) == 1
    viejo, nuevo = renombrada[0]
    assert viejo["valido_hasta"] == nuevo["valido_desde"] and nuevo["valido_hasta"] is None


def test_reprocesar_no_duplica():
    s = Silver()
    lotes = [leer("cdc_2026-09-25_mismas_claves.jsonl"), leer("cdc_2026-09-26.jsonl")]
    for lote in lotes + lotes:
        s.aplicar(lote)
    assert s.filas() == 18


def test_update_sin_cambios_reales_no_abre_version():
    s = Silver()
    base = {"lei": "L1", "orden": 1, "nombre": "ACME SA", "modificado_en": "t1"}
    s.aplicar([cambio("insert", 1, base), cambio("update", 2, {**base, "modificado_en": "t2"})])
    assert s.filas() == 1


def test_update_antes_se_descarta_y_orden_por_lsn():
    s = Silver()
    a = {"lei": "L1", "orden": 1, "nombre": "A"}
    s.aplicar([cambio("update", 3, {**a, "nombre": "C"}), cambio("update_antes", 3, {**a, "nombre": "B"}),
               cambio("insert", 1, a), cambio("update", 2, {**a, "nombre": "B"})])
    assert [v["nombre"] for v in s.hist[("nombre_alternativo", "L1", 1)]] == ["A", "B", "C"]
    assert s.vigentes()[("nombre_alternativo", "L1", 1)]["nombre"] == "C"


def test_delete_cierra_sin_abrir_y_reinsert():
    s = Silver()
    a = {"lei": "L1", "orden": 1, "nombre": "A"}
    s.aplicar([cambio("insert", 1, a)])
    s.aplicar([cambio("delete", 2, a, ts="2026-09-27T10:00:00")])
    v = s.hist[("nombre_alternativo", "L1", 1)]
    assert len(v) == 1 and v[0]["valido_hasta"] == "2026-09-27T10:00:00" and not s.vigentes()
    s.aplicar([cambio("delete", 2, a, ts="2026-09-27T10:00:00")])      # reproceso del delete
    assert len(v) == 1
    s.aplicar([cambio("insert", 3, a)])                                   # vuelve a aparecer
    assert len(v) == 2 and s.vigentes()


def test_delete_e_insert_en_el_mismo_lote():
    s = Silver()
    a = {"lei": "L1", "orden": 1, "nombre": "A"}
    s.aplicar([cambio("insert", 1, a), cambio("delete", 2, a), cambio("insert", 3, {**a, "nombre": "A2"})])
    v = s.hist[("nombre_alternativo", "L1", 1)]
    assert [(x["nombre"], x["valido_hasta"] is None) for x in v] == [("A", False), ("A2", True)]
