"""Fase 2 (regla 04): carga del ERP "legacy" (SQL Server) con datos reales de GLEIF.

Comandos:
    carga-inicial   Golden copy completo (LEI2 + RR) -> universo -> MERGE en erp.*.
    delta           Delta de GLEIF (LastDay, o LastWeek si la última aplicación tiene más de
                    un día) sobre las entidades del universo: altas, cambios y bajas lógicas.

Universo (decisión de fase 2):
    universo_ar  domicilio legal o jurisdicción AR (965 al 2026-09-24)
    sede_ar      no argentinas con sede (headquarters) en AR (55)
    control      contrapartes no argentinas de relaciones RR con las anteriores

Reglas de escritura:
- MERGE con detección de cambios: una fila solo se actualiza si cambió algún campo. Re-aplicar
  el mismo archivo no genera updates falsos en el CDC.
- Bajas lógicas: GLEIF nunca borra un LEI; la baja llega como cambio de estado
  (RETIRED, ANNULLED, ...), y así se aplica.
- etl.aplicacion_gleif registra cada archivo aplicado (sha256): un archivo no se aplica dos veces.

La contraseña de sa se lee de legacy/.env (fuera de git) y nunca se imprime.

Uso:
    python legacy/gleif_erp.py carga-inicial [--dir legacy/data/gleif]
    python legacy/gleif_erp.py delta [--tipo auto|LastDay|LastWeek] [--dir legacy/data/gleif]
"""

import argparse
import hashlib
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pymssql
import requests

RAIZ = Path(__file__).resolve().parent
API = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"

L = "Entity.LegalAddress."
H = "Entity.HeadquartersAddress."
COLS_ENTIDAD = [
    "LEI", "Entity.LegalName", "Entity.LegalName.xmllang", "Entity.LegalJurisdiction",
    "Entity.EntityCategory", "Entity.LegalForm.EntityLegalFormCode", "Entity.LegalForm.OtherLegalForm",
    "Entity.EntityStatus", "Entity.EntityCreationDate", "Registration.RegistrationStatus",
    "Registration.InitialRegistrationDate", "Registration.LastUpdateDate",
    "Registration.NextRenewalDate", "Registration.ManagingLOU",
]
CAMPOS_DIR = ["FirstAddressLine", "AddressNumber", "AdditionalAddressLine.1", "City", "Region",
              "Country", "PostalCode"]
COLS_RR = ["Relationship.StartNode.NodeID", "Relationship.EndNode.NodeID",
           "Relationship.RelationshipType", "Relationship.RelationshipStatus",
           "Registration.RegistrationStatus", "Relationship.Period.1.startDate",
           "Registration.LastUpdateDate"]


# --------------------------------------------------------------------------- conexión

def conectar() -> pymssql.Connection:
    env = dict(l.split("=", 1) for l in (RAIZ / ".env").read_text(encoding="utf-8").splitlines() if "=" in l)
    return pymssql.connect(server="127.0.0.1", port=1433, user="sa", password=env["MSSQL_SA_PASSWORD"],
                           database="entity360_erp", autocommit=False, charset="UTF-8")


# --------------------------------------------------------------------------- archivos GLEIF

def bajar(url: str, carpeta: Path) -> tuple[Path, str]:
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / url.rsplit("/", 1)[1]
    if not destino.exists():
        t0 = time.perf_counter()
        tmp = destino.with_suffix(".part")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for b in r.iter_content(8 << 20):
                    f.write(b)
        tmp.rename(destino)
        print(f"  bajado {destino.name} ({destino.stat().st_size / 2**20:,.1f} MB, {time.perf_counter() - t0:,.1f} s)")
    h = hashlib.sha256()
    with open(destino, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return destino, h.hexdigest()


def leer_csv_zip(ruta: Path, columnas=None) -> pa.Table:
    with zipfile.ZipFile(ruta) as z, z.open(z.namelist()[0]) as f:
        if columnas is None:
            return pacsv.read_csv(f, read_options=pacsv.ReadOptions(block_size=64 << 20),
                                  convert_options=pacsv.ConvertOptions(strings_can_be_null=True))
        return pacsv.read_csv(f, read_options=pacsv.ReadOptions(block_size=64 << 20),
                              convert_options=pacsv.ConvertOptions(
                                  include_columns=columnas, strings_can_be_null=True,
                                  column_types={c: pa.string() for c in columnas}))


def columnas_lei2(ruta: Path) -> list[str]:
    """Columnas necesarias, incluidas todas las de nombres alternativos que traiga el archivo."""
    with zipfile.ZipFile(ruta) as z, z.open(z.namelist()[0]) as f:
        cabecera = f.readline().decode("utf-8").strip().replace('"', "").split(",")
    otros = [c for c in cabecera if re.fullmatch(r"Entity\.OtherEntityNames\.OtherEntityName\.\d+(\.xmllang|\.type)?", c)]
    return COLS_ENTIDAD + [p + c for p in (L, H) for c in CAMPOS_DIR] + otros


# --------------------------------------------------------------------------- universo

def es_ar(t: pa.Table, prefijo_pais: str) -> pa.ChunkedArray:
    return pc.fill_null(pc.equal(t[prefijo_pais + "Country"], "AR"), False)


def alcance_base(t: pa.Table) -> dict[str, str]:
    jur = t["Entity.LegalJurisdiction"]
    ar = pc.or_(es_ar(t, L), pc.fill_null(pc.or_(pc.equal(jur, "AR"), pc.starts_with(jur, "AR-")), False))
    sede = pc.and_(pc.invert(ar), es_ar(t, H))
    alcance = {lei: "universo_ar" for lei in t.filter(ar)["LEI"].to_pylist()}
    alcance.update({lei: "sede_ar" for lei in t.filter(sede)["LEI"].to_pylist()})
    return alcance


# --------------------------------------------------------------------------- transformación

def fecha(v):
    return v[:10] if v else None


def filas_entidad(t: pa.Table, alcance: dict[str, str]) -> list[tuple]:
    out = []
    for r in t.to_pylist():
        out.append((
            r["LEI"], r["Entity.LegalName"], r["Entity.LegalName.xmllang"], r["Entity.LegalJurisdiction"],
            r["Entity.EntityCategory"], r["Entity.LegalForm.EntityLegalFormCode"],
            r["Entity.LegalForm.OtherLegalForm"], r["Entity.EntityStatus"] or "NULL",
            fecha(r["Entity.EntityCreationDate"]), r["Registration.RegistrationStatus"] or "NULL",
            r["Registration.InitialRegistrationDate"], r["Registration.LastUpdateDate"],
            r["Registration.NextRenewalDate"], r["Registration.ManagingLOU"], alcance[r["LEI"]],
        ))
    return out


def filas_direccion(t: pa.Table) -> list[tuple]:
    out = []
    for r in t.to_pylist():
        for tipo, p in (("LEGAL", L), ("SEDE", H)):
            out.append((r["LEI"], tipo, r[p + "FirstAddressLine"], r[p + "AddressNumber"],
                        r[p + "AdditionalAddressLine.1"], r[p + "City"], r[p + "Region"],
                        r[p + "Country"], r[p + "PostalCode"]))
    return out


def filas_nombre(t: pa.Table) -> list[tuple]:
    indices = sorted({int(m.group(1)) for c in t.column_names
                      if (m := re.fullmatch(r"Entity\.OtherEntityNames\.OtherEntityName\.(\d+)", c))})
    out = []
    for r in t.to_pylist():
        for i in indices:
            base = f"Entity.OtherEntityNames.OtherEntityName.{i}"
            if r.get(base):
                out.append((r["LEI"], i, r[base], r.get(base + ".type"), r.get(base + ".xmllang")))
    return out


def filas_relacion(rr: pa.Table, leis: set[str]) -> tuple[list[tuple], int]:
    out, fuera = [], 0
    for r in rr.to_pylist():
        hijo, padre = r["Relationship.StartNode.NodeID"], r["Relationship.EndNode.NodeID"]
        if hijo in leis and padre in leis:
            out.append((hijo, padre, r["Relationship.RelationshipType"], r["Relationship.RelationshipStatus"],
                        r["Registration.RegistrationStatus"], r["Relationship.Period.1.startDate"],
                        r["Registration.LastUpdateDate"]))
        elif hijo in leis or padre in leis:
            fuera += 1
    return out, fuera


# --------------------------------------------------------------------------- MERGE

TABLAS = {
    "entidad": {
        "clave": ["lei"],
        "cols": ["lei", "nombre_legal", "idioma_nombre", "jurisdiccion", "categoria", "forma_juridica_codigo",
                 "forma_juridica_otra", "estado_entidad", "fecha_creacion_entidad", "estado_registro",
                 "fecha_registro_inicial", "fecha_ultima_actualizacion", "fecha_proxima_renovacion",
                 "lou_gestor", "alcance"],
        "tipos": ["CHAR(20)", "NVARCHAR(500)", "VARCHAR(10)", "VARCHAR(10)", "VARCHAR(30)", "VARCHAR(10)",
                  "NVARCHAR(200)", "VARCHAR(20)", "DATE", "VARCHAR(30)", "DATETIMEOFFSET", "DATETIMEOFFSET",
                  "DATETIMEOFFSET", "CHAR(20)", "VARCHAR(20)"],
        # El alcance no se pisa en los deltas: una entidad de control sigue siendo de control.
        "sin_update": ["alcance"],
    },
    "direccion": {
        "clave": ["lei", "tipo"],
        "cols": ["lei", "tipo", "linea1", "numero", "linea_adicional", "ciudad", "region", "pais", "codigo_postal"],
        "tipos": ["CHAR(20)", "VARCHAR(10)", "NVARCHAR(500)", "NVARCHAR(50)", "NVARCHAR(500)", "NVARCHAR(200)",
                  "VARCHAR(10)", "CHAR(2)", "NVARCHAR(50)"],
    },
    "nombre_alternativo": {
        "clave": ["lei", "orden"],
        "cols": ["lei", "orden", "nombre", "tipo", "idioma"],
        "tipos": ["CHAR(20)", "TINYINT", "NVARCHAR(500)", "VARCHAR(60)", "VARCHAR(10)"],
        # Si GLEIF deja de informar un nombre de una entidad del lote, se borra (dato real).
        "borrar_faltantes_de_leis": True,
    },
    "relacion": {
        "clave": ["lei_hijo", "lei_padre", "tipo"],
        "cols": ["lei_hijo", "lei_padre", "tipo", "estado_relacion", "estado_registro", "fecha_inicio",
                 "fecha_ultima_actualizacion"],
        "tipos": ["CHAR(20)", "CHAR(20)", "VARCHAR(40)", "VARCHAR(20)", "VARCHAR(30)", "DATETIMEOFFSET",
                  "DATETIMEOFFSET"],
    },
}


def merge(cur, tabla: str, filas: list[tuple], leis_lote: list[str] | None = None) -> dict[str, int]:
    d = TABLAS[tabla]
    cols, clave = d["cols"], d["clave"]
    # Una fila por clave (la última gana): un MERGE con claves repetidas en la fuente falla.
    idx = [cols.index(c) for c in clave]
    filas = list({tuple(f[i] for i in idx): f for f in filas}.values())
    cur.execute(f"CREATE TABLE #s ({', '.join(f'{c} {t}' for c, t in zip(cols, d['tipos']))})")
    if filas:
        cur.executemany(f"INSERT INTO #s VALUES ({', '.join(['%s'] * len(cols))})", filas)
    upd = [c for c in cols if c not in clave and c not in d.get("sin_update", [])]
    on = " AND ".join(f"t.{c} = s.{c}" for c in clave)
    borrar = ""
    if d.get("borrar_faltantes_de_leis"):
        # Entidades del lote (aunque no traigan ningún nombre): lo que ya no informa GLEIF se borra.
        cur.execute("CREATE TABLE #leis (lei CHAR(20) PRIMARY KEY)")
        if leis_lote:
            cur.executemany("INSERT INTO #leis VALUES (%s)", [(x,) for x in sorted(set(leis_lote))])
        borrar = "WHEN NOT MATCHED BY SOURCE AND t.lei IN (SELECT lei FROM #leis) THEN DELETE"
    cur.execute(f"""
        SET NOCOUNT ON;
        DECLARE @acciones TABLE (accion NVARCHAR(10));
        MERGE erp.{tabla} AS t
        USING #s AS s ON {on}
        WHEN MATCHED AND EXISTS (SELECT {', '.join('s.' + c for c in upd)}
                                 EXCEPT SELECT {', '.join('t.' + c for c in upd)})
            THEN UPDATE SET {', '.join(f't.{c} = s.{c}' for c in upd)}, t.modificado_en = SYSUTCDATETIME()
        WHEN NOT MATCHED BY TARGET
            THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)})
        {borrar}
        OUTPUT $action INTO @acciones;
        SELECT accion, COUNT(*) FROM @acciones GROUP BY accion;
    """)
    res = {a: n for a, n in cur.fetchall()}
    cur.execute("DROP TABLE #s")
    if d.get("borrar_faltantes_de_leis"):
        cur.execute("DROP TABLE #leis")
    return {"insert": res.get("INSERT", 0), "update": res.get("UPDATE", 0), "delete": res.get("DELETE", 0)}


def ya_aplicado(cur, archivo: str) -> bool:
    cur.execute("SELECT 1 FROM etl.aplicacion_gleif WHERE archivo = %s", (archivo,))
    return cur.fetchone() is not None


def registrar(cur, archivo, tipo, publicacion, sha, leidas, totales):
    cur.execute("INSERT INTO etl.aplicacion_gleif (archivo, tipo, publicacion, sha256, filas_leidas, insertadas, "
                "actualizadas) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (archivo, tipo, publicacion, sha, leidas,
                 sum(t["insert"] for t in totales.values()), sum(t["update"] for t in totales.values())))


# --------------------------------------------------------------------------- comandos

def carga_inicial(carpeta: Path) -> int:
    meta = requests.get(API, timeout=60).json()["data"]
    publicacion = meta["publish_date"]
    print(f"publicación GLEIF: {publicacion}")
    lei2, sha_lei2 = bajar(meta["lei2"]["full_file"]["csv"]["url"], carpeta)
    rr_ruta, sha_rr = bajar(meta["rr"]["full_file"]["csv"]["url"], carpeta)

    con = conectar()
    cur = con.cursor()
    if ya_aplicado(cur, lei2.name):
        print(f"{lei2.name} ya estaba aplicado: nada que hacer (idempotente).")
        return 0

    t0 = time.perf_counter()
    t = leer_csv_zip(lei2, columnas_lei2(lei2))
    rr = leer_csv_zip(rr_ruta, COLS_RR)
    print(f"leídos LEI2 {t.num_rows:,} y RR {rr.num_rows:,} en {time.perf_counter() - t0:,.1f} s")

    alcance = alcance_base(t)
    base = set(alcance)
    for a, b in zip(rr["Relationship.StartNode.NodeID"].to_pylist(), rr["Relationship.EndNode.NodeID"].to_pylist()):
        for x, y in ((a, b), (b, a)):
            if x in base and y not in base:
                alcance.setdefault(y, "control")
    sub = t.filter(pc.is_in(t["LEI"], value_set=pa.array(sorted(alcance))))
    faltan = len(alcance) - sub.num_rows
    print(f"universo: {sum(v == 'universo_ar' for v in alcance.values())} universo_ar, "
          f"{sum(v == 'sede_ar' for v in alcance.values())} sede_ar, "
          f"{sum(v == 'control' for v in alcance.values())} control; "
          f"{sub.num_rows} con registro en LEI2 ({faltan} contrapartes sin LEI2 se omiten)")
    alcance = {k: v for k, v in alcance.items() if k in set(sub["LEI"].to_pylist())}

    rels, fuera = filas_relacion(rr, set(alcance))
    totales = {
        "entidad": merge(cur, "entidad", filas_entidad(sub, alcance)),
        "direccion": merge(cur, "direccion", filas_direccion(sub)),
        "nombre_alternativo": merge(cur, "nombre_alternativo", filas_nombre(sub), sub["LEI"].to_pylist()),
        "relacion": merge(cur, "relacion", rels),
    }
    registrar(cur, lei2.name, "full", publicacion, sha_lei2, sub.num_rows, totales)
    registrar(cur, rr_ruta.name, "full", publicacion, sha_rr, len(rels), {})
    con.commit()
    print(f"relaciones RR no cargadas (una punta fuera del ERP, típicamente de entidades de control): {fuera}")
    for k, v in totales.items():
        print(f"  erp.{k:18} {v}")
    print(f"carga inicial: {time.perf_counter() - t0:,.1f} s")
    return 0


def delta(carpeta: Path, tipo: str) -> int:
    con = conectar()
    cur = con.cursor()
    cur.execute("SELECT MAX(publicacion) FROM etl.aplicacion_gleif")
    ultima = cur.fetchone()[0]
    if not ultima:
        print("No hay carga inicial: correr primero 'carga-inicial'.")
        return 2
    if tipo == "auto":
        horas = (datetime.now(timezone.utc) - datetime.fromisoformat(ultima.replace(" ", "T")).replace(
            tzinfo=timezone.utc)).total_seconds() / 3600
        tipo = "LastDay" if horas <= 24 else "LastWeek"
        print(f"última publicación aplicada: {ultima} (hace {horas:,.1f} h) -> delta {tipo}")

    meta = requests.get(API, timeout=60).json()["data"]
    publicacion = meta["publish_date"]
    lei2, sha_lei2 = bajar(meta["lei2"]["delta_files"][tipo]["csv"]["url"], carpeta)
    rr_ruta, sha_rr = bajar(meta["rr"]["delta_files"][tipo]["csv"]["url"], carpeta)
    if ya_aplicado(cur, lei2.name):
        print(f"{lei2.name} ya estaba aplicado: nada que hacer (idempotente).")
        return 0

    cur.execute("SELECT lei, alcance FROM erp.entidad")
    alcance = {lei: a for lei, a in cur.fetchall()}
    t = leer_csv_zip(lei2, columnas_lei2(lei2))
    # Altas: entidades nuevas que entran al universo base. Cambios y bajas: las que ya están.
    nuevas = {k: v for k, v in alcance_base(t).items() if k not in alcance}
    alcance.update(nuevas)
    sub = t.filter(pc.is_in(t["LEI"], value_set=pa.array(sorted(alcance))))
    rr = leer_csv_zip(rr_ruta, COLS_RR)
    rels, fuera = filas_relacion(rr, set(alcance))
    print(f"delta {tipo} ({publicacion}): {t.num_rows:,} registros LEI2, {sub.num_rows} del universo "
          f"({len(nuevas)} altas candidatas); RR {rr.num_rows:,}, {len(rels)} del universo, {fuera} con una punta afuera")

    totales = {
        "entidad": merge(cur, "entidad", filas_entidad(sub, alcance)),
        "direccion": merge(cur, "direccion", filas_direccion(sub)),
        "nombre_alternativo": merge(cur, "nombre_alternativo", filas_nombre(sub), sub["LEI"].to_pylist()),
        "relacion": merge(cur, "relacion", rels),
    }
    registrar(cur, lei2.name, f"delta_{tipo}", publicacion, sha_lei2, sub.num_rows, totales)
    registrar(cur, rr_ruta.name, f"delta_{tipo}", publicacion, sha_rr, len(rels), {})
    con.commit()
    for k, v in totales.items():
        print(f"  erp.{k:18} {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["carga-inicial", "delta"])
    ap.add_argument("--dir", type=Path, default=RAIZ / "data" / "gleif")
    ap.add_argument("--tipo", choices=["auto", "LastDay", "LastWeek"], default="auto")
    a = ap.parse_args()
    return carga_inicial(a.dir) if a.comando == "carga-inicial" else delta(a.dir, a.tipo)


if __name__ == "__main__":
    sys.exit(main())
