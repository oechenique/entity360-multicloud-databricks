"""Spike B.8: GLEIF golden copy completo, leído en streaming (sin descomprimir a disco).

1. Metadata del último publish (fecha, tamaños, registros, deltas).
2. Descarga de LEI2 y RR (CSV zip) a spike/data/ (ignorado por git), midiendo el tiempo.
   Si el archivo del mismo publish ya está, no se vuelve a bajar.
3. LEI2, pasada completa con csv (stdlib): total, AR por domicilio legal y por
   jurisdicción, estados. Mide tiempo y filas/s.
4. LEI2, pasada completa con pyarrow.csv (streaming por bloques): mismo conteo de AR,
   para comparar tiempos.
5. RR: relaciones donde alguna punta es una entidad AR.

Licencia: GLEIF golden copy, CC0 1.0.

Uso:
    spike\\.venv\\Scripts\\python.exe spike\\scripts\\b8_gleif_golden_copy.py
"""

import csv
import io
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

import requests

API = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"
DATA = Path(__file__).resolve().parents[1] / "data" / "gleif"

COL_LEI = "LEI"
COL_PAIS = "Entity.LegalAddress.Country"
COL_JURIS = "Entity.LegalJurisdiction"
COL_ESTADO = "Entity.EntityStatus"
COL_REG = "Registration.RegistrationStatus"


def mb(n: int) -> str:
    return f"{n / 1024 / 1024:,.1f} MB"


def bajar(url: str, destino: Path) -> float:
    if destino.exists():
        print(f"  ya existe {destino.name} ({mb(destino.stat().st_size)}), no se baja de nuevo")
        return 0.0
    t0 = time.perf_counter()
    tmp = destino.with_suffix(".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloque in r.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(bloque)
    tmp.rename(destino)
    seg = time.perf_counter() - t0
    print(f"  bajado {destino.name}: {mb(destino.stat().st_size)} en {seg:,.1f} s")
    return seg


def abrir_csv_del_zip(ruta: Path):
    z = zipfile.ZipFile(ruta)
    miembro = z.namelist()[0]
    info = z.getinfo(miembro)
    print(f"  miembro {miembro}: {mb(info.compress_size)} comprimido, {mb(info.file_size)} descomprimido")
    return z, z.open(miembro)


def es_ar(pais: str, juris: str) -> tuple[bool, bool]:
    return pais == "AR", juris == "AR" or juris.startswith("AR-")


def pasada_stdlib(ruta: Path) -> tuple[dict, set[str]]:
    z, crudo = abrir_csv_del_zip(ruta)
    with z, crudo:
        lector = csv.reader(io.TextIOWrapper(crudo, encoding="utf-8", newline=""))
        cab = next(lector)
        print(f"  columnas: {len(cab)}")
        i = {c: cab.index(c) for c in (COL_LEI, COL_PAIS, COL_JURIS, COL_ESTADO, COL_REG)}
        total, ar_dom, ar_jur, ar_union = 0, 0, 0, set()
        estados, regs = Counter(), Counter()
        t0 = time.perf_counter()
        for fila in lector:
            total += 1
            dom, jur = es_ar(fila[i[COL_PAIS]], fila[i[COL_JURIS]])
            if dom or jur:
                ar_union.add(fila[i[COL_LEI]])
                estados[fila[i[COL_ESTADO]]] += 1
                regs[fila[i[COL_REG]]] += 1
            ar_dom += dom
            ar_jur += jur
        seg = time.perf_counter() - t0
    return {
        "lector": "csv (stdlib)",
        "total": total,
        "ar_domicilio_legal": ar_dom,
        "ar_jurisdiccion": ar_jur,
        "ar_union": len(ar_union),
        "ar_entity_status": dict(estados),
        "ar_registration_status": dict(regs),
        "segundos": round(seg, 1),
        "filas_por_segundo": round(total / seg),
    }, ar_union


def pasada_pyarrow(ruta: Path) -> dict:
    import pyarrow.compute as pc
    import pyarrow.csv as pacsv

    z, crudo = abrir_csv_del_zip(ruta)
    with z, crudo:
        t0 = time.perf_counter()
        lector = pacsv.open_csv(
            crudo,
            read_options=pacsv.ReadOptions(block_size=64 * 1024 * 1024),
            convert_options=pacsv.ConvertOptions(
                include_columns=[COL_LEI, COL_PAIS, COL_JURIS],
                column_types={COL_LEI: "string", COL_PAIS: "string", COL_JURIS: "string"},
            ),
        )
        total, ar_dom, ar_jur, ar_union = 0, 0, 0, 0
        for lote in lector:
            total += lote.num_rows
            dom = pc.equal(lote.column(COL_PAIS), "AR")
            jur = pc.or_(pc.equal(lote.column(COL_JURIS), "AR"),
                         pc.starts_with(lote.column(COL_JURIS), "AR-"))
            dom = pc.fill_null(dom, False)
            jur = pc.fill_null(jur, False)
            ar_dom += pc.sum(dom).as_py() or 0
            ar_jur += pc.sum(jur).as_py() or 0
            ar_union += pc.sum(pc.or_(dom, jur)).as_py() or 0
        seg = time.perf_counter() - t0
    return {
        "lector": "pyarrow.csv (streaming, 3 columnas)",
        "total": total,
        "ar_domicilio_legal": ar_dom,
        "ar_jurisdiccion": ar_jur,
        "ar_union": ar_union,
        "segundos": round(seg, 1),
        "filas_por_segundo": round(total / seg),
    }


def pasada_rr(ruta: Path, leis_ar: set[str]) -> dict:
    z, crudo = abrir_csv_del_zip(ruta)
    with z, crudo:
        lector = csv.reader(io.TextIOWrapper(crudo, encoding="utf-8", newline=""))
        cab = next(lector)
        ini = cab.index("Relationship.StartNode.NodeID")
        fin = cab.index("Relationship.EndNode.NodeID")
        tipo = cab.index("Relationship.RelationshipType")
        total, tipos = 0, Counter()
        t0 = time.perf_counter()
        for fila in lector:
            total += 1
            if fila[ini] in leis_ar or fila[fin] in leis_ar:
                tipos[fila[tipo]] += 1
        seg = time.perf_counter() - t0
    return {"total": total, "con_punta_ar": sum(tipos.values()), "por_tipo": dict(tipos),
            "segundos": round(seg, 1)}


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    meta = requests.get(API, timeout=60).json()["data"]
    print("=== 1. metadata del publish ===")
    print(f"publish_date: {meta['publish_date']}")
    resumen = {"publish_date": meta["publish_date"], "licencia": "CC0 1.0", "archivos": {}}
    for tipo in ("lei2", "rr"):
        full = meta[tipo]["full_file"]["csv"]
        last_day = meta[tipo]["delta_files"]["LastDay"]["csv"]
        resumen["archivos"][tipo] = {
            "full": {"size": full["size_human_readable"], "records": full["record_count"]},
            "delta_last_day": {"size": last_day["size_human_readable"], "records": last_day["record_count"]},
        }
        print(f"{tipo}: full {full['size_human_readable']} / {full['record_count']:,} registros | "
              f"delta LastDay {last_day['size_human_readable']} / {last_day['record_count']:,} registros")

    print("\n=== 2. descarga ===")
    rutas = {}
    for tipo in ("lei2", "rr"):
        url = meta[tipo]["full_file"]["csv"]["url"]
        rutas[tipo] = DATA / url.rsplit("/", 1)[1]
        resumen["archivos"][tipo]["descarga_segundos"] = round(bajar(url, rutas[tipo]), 1)

    print("\n=== 3. LEI2 con csv (stdlib), archivo entero ===")
    stdlib, leis_ar = pasada_stdlib(rutas["lei2"])
    print(json.dumps(stdlib, indent=2, ensure_ascii=False))

    print("\n=== 4. LEI2 con pyarrow.csv, archivo entero ===")
    arrow = pasada_pyarrow(rutas["lei2"])
    print(json.dumps(arrow, indent=2, ensure_ascii=False))
    coinciden = all(stdlib[k] == arrow[k] for k in ("total", "ar_domicilio_legal", "ar_jurisdiccion", "ar_union"))
    print(f"conteos stdlib vs pyarrow coinciden: {coinciden}")

    print("\n=== 5. RR: relaciones con alguna punta AR ===")
    rr = pasada_rr(rutas["rr"], leis_ar)
    print(json.dumps(rr, indent=2, ensure_ascii=False))

    resumen.update({"lei2_stdlib": stdlib, "lei2_pyarrow": arrow, "rr": rr, "conteos_coinciden": coinciden})
    print("\n=== resumen JSON ===")
    print(json.dumps(resumen, ensure_ascii=False))
    return 0 if coinciden else 1


if __name__ == "__main__":
    sys.exit(main())
