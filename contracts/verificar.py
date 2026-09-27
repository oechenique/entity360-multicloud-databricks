"""Contratos de llegada (regla 09): verifica cada lote del landing antes de que entre a Bronze.

Por lote (<fuente>_<ts>.jsonl + _manifest_<ts>.json):
1. Integridad contra el manifest: sha256 del archivo y cantidad de registros (crítico).
2. El lote se carga en DuckDB (tabla `crudo`), se proyecta con contracts/<fuente>.sql (vista `lote`) y
   se verifica con el contrato de Soda Core contracts/<fuente>.yml. Si la proyección falla (cambió el
   formato de la fuente), es crítico.
3. Veredicto: `aprobado` si no falló ningún check crítico; si no, `cuarentena`. Las advertencias
   (`level: warn`) no frenan el lote. Se escribe `_contrato_<ts>.json` junto al manifest: Bronze no
   ingiere un lote en cuarentena.
4. Una cuarentena genera una alerta (alertas.py). Las demás fuentes siguen su camino.

La frescura se mide contra el `extraido_utc` del manifest, no contra la hora de la verificación: un
lote verificado tarde (la PC estaba apagada) o re-verificado da el mismo veredicto.

Uso (entorno contracts\\.venv, perfil de la CLI de Databricks):
    contracts\\.venv\\Scripts\\python.exe contracts\\verificar.py --pendientes [--fuente gdelt]
    contracts\\.venv\\Scripts\\python.exe contracts\\verificar.py --archivo lote.jsonl --manifest m.json --fuente gdelt
"""

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from soda_core.contracts.api.verify_api import verify_contract_locally
from soda_core.contracts.contract_verification import CheckOutcome

import soda_duckdb.common.data_sources.duckdb_data_source as soda_duckdb  # después de soda_core (import circular)

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import alertas  # noqa: E402

VERSION = "contratos-1.0"
FUENTES = ("sqlserver_cdc", "sec_edgar", "gdelt", "opensanctions", "wikidata")
RAW = "/Volumes/entity360/landing/raw"


# ------------------------------------------------------------------ verificación de un lote

def _check(nombre: str, critico: bool, ok: bool, detalle: dict | str | None = None) -> dict:
    return {"check": nombre, "critico": critico, "resultado": "ok" if ok else "falla", "detalle": detalle}


def _nombre_check(c) -> str:
    partes = [c.check.type]
    if c.check.column_name:
        partes.append(c.check.column_name)
    if c.check.qualifier:
        partes.append(c.check.qualifier)
    elif c.check.type == "failed_rows" and c.check.name:     # el resto trae como nombre el texto del resultado
        partes.append(c.check.name)
    return " ".join(partes)


def _critico(c) -> bool:
    """`level: warn` en el umbral = aviso; lo demás (incluido schema, sin umbral) es crítico."""
    return getattr(c.check.threshold, "level", "fail") != "warn"


def verificar(fuente: str, contenido: bytes, manifest: dict) -> dict:
    """Veredicto del lote. Python puro más DuckDB y Soda, sin red: los tests lo llaman directo."""
    checks = []
    sha = hashlib.sha256(contenido).hexdigest()
    lineas = sum(1 for l in contenido.decode("utf-8").split("\n") if l.strip())
    checks.append(_check("sha256 del manifest", True, sha == manifest.get("sha256"),
                         None if sha == manifest.get("sha256") else f"archivo {sha[:12]}…, manifest {str(manifest.get('sha256'))[:12]}…"))
    checks.append(_check("registros del manifest", True, lineas == manifest.get("registros"),
                         {"lineas": lineas, "manifest": manifest.get("registros")}))

    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "lote.jsonl"
        ruta.write_bytes(contenido)
        try:
            con.execute("CREATE TABLE crudo AS SELECT * FROM read_json(?, format='newline_delimited', "
                        "maximum_object_size=104857600)", [str(ruta)])
            con.execute("CREATE VIEW lote AS " + (AQUI / f"{fuente}.sql").read_text(encoding="utf-8"))
            con.execute("SELECT * FROM lote LIMIT 1").fetchall()
            proyeccion_ok, error = True, None
        except duckdb.Error as e:
            proyeccion_ok, error = False, str(e).splitlines()[0][:300]
        checks.append(_check("proyección del formato de la fuente", True, proyeccion_ok, error))

        if proyeccion_ok:
            ds = soda_duckdb.DuckDBDataSourceImpl.from_existing_cursor(con, "lote")
            r = verify_contract_locally(data_sources=[ds], contract_file_path=str(AQUI / f"{fuente}.yml"),
                                        data_timestamp=manifest.get("extraido_utc"))
            if r.has_errors:
                checks.append(_check("contrato de Soda", True, False, r.get_errors_str()[:500]))
            for cvr in r.contract_verification_results:
                for c in cvr.check_results:
                    # outcome y no is_passed/is_excluded: en Soda 4.25 is_excluded es un método (siempre truthy).
                    # NOT_EVALUATED (el check no pudo correr) cuenta como falla.
                    ok = c.outcome in (CheckOutcome.PASSED, CheckOutcome.EXCLUDED)
                    checks.append(_check(_nombre_check(c), _critico(c) and c.outcome != CheckOutcome.WARN, ok,
                                         {k: v for k, v in (c.diagnostic_metric_values or {}).items()
                                          if not k.endswith("rows_tested")} or None))
    con.close()

    fallas = [c for c in checks if c["resultado"] == "falla" and c["critico"]]
    avisos = [c for c in checks if c["resultado"] == "falla" and not c["critico"]]
    return {"fuente": fuente, "archivo": manifest.get("archivo"), "sha256": sha,
            "estado": "cuarentena" if fallas else "aprobado",
            "fallas_criticas": [c["check"] for c in fallas], "advertencias": [c["check"] for c in avisos],
            "checks": checks, "verificado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "version": VERSION}


def contrato_de(ruta_datos: str) -> str:
    """<carpeta>/<fuente>_<ts>.jsonl -> <carpeta>/_contrato_<ts>.json (junto al manifest)."""
    carpeta, archivo = ruta_datos.rsplit("/", 1)
    ts = archivo.rsplit(".", 1)[0].rsplit("_", 1)[1]
    return f"{carpeta}/_contrato_{ts}.json"


# ------------------------------------------------------------------ lotes del volume

def _cliente():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_CONFIG_PROFILE", "entity360-free"))


def _leer(w, ruta: str) -> bytes:
    return w.files.download(ruta).contents.read()


def pendientes(w, fuente: str) -> list[str]:
    """Archivos de datos con manifest y sin veredicto todavía."""
    out = []
    for d in w.files.list_directory_contents(f"{RAW}/{fuente}"):
        if not d.is_directory:
            continue
        nombres = {e.name for e in w.files.list_directory_contents(d.path)}
        for n in sorted(nombres):
            if n.endswith(".jsonl"):
                ruta = f"{d.path.rstrip('/')}/{n}"
                ts = n.rsplit(".", 1)[0].rsplit("_", 1)[1]
                if f"_manifest_{ts}.json" in nombres and f"_contrato_{ts}.json" not in nombres:
                    out.append(ruta)
    return out


def procesar(w, fuente: str, ruta: str) -> dict:
    carpeta, archivo = ruta.rsplit("/", 1)
    ts = archivo.rsplit(".", 1)[0].rsplit("_", 1)[1]
    manifest = json.loads(_leer(w, f"{carpeta}/_manifest_{ts}.json"))
    v = verificar(fuente, _leer(w, ruta), manifest)
    w.files.upload(contrato_de(ruta), io.BytesIO(json.dumps(v, ensure_ascii=False, indent=2).encode()), overwrite=True)
    if v["estado"] == "cuarentena":
        alertas.enviar(f"entity360: lote en cuarentena ({fuente})",
                       f"{archivo}\nFallas críticas: {', '.join(v['fallas_criticas'])}\n"
                       f"El lote no entra a Bronze. Veredicto: {contrato_de(ruta)}")
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuente", choices=FUENTES)
    ap.add_argument("--pendientes", action="store_true", help="verifica los lotes del volume sin veredicto")
    ap.add_argument("--archivo", help="lote local (sin volume)")
    ap.add_argument("--manifest", help="manifest local del lote")
    a = ap.parse_args()
    if a.archivo:
        v = verificar(a.fuente, Path(a.archivo).read_bytes(), json.loads(Path(a.manifest).read_text(encoding="utf-8")))
        print(json.dumps(v, ensure_ascii=False, indent=2, default=str))
        return 0 if v["estado"] == "aprobado" else 1
    if not a.pendientes:
        ap.error("--pendientes o --archivo")
    w = _cliente()
    cuarentenas = 0
    for fuente in [a.fuente] if a.fuente else FUENTES:
        for ruta in pendientes(w, fuente):
            v = procesar(w, fuente, ruta)
            cuarentenas += v["estado"] == "cuarentena"
            aviso = f" | avisos: {', '.join(v['advertencias'])}" if v["advertencias"] else ""
            print(f"{fuente}: {ruta.rsplit('/', 1)[1]} -> {v['estado']}"
                  f"{' (' + ', '.join(v['fallas_criticas']) + ')' if v['fallas_criticas'] else ''}{aviso}")
    # Una cuarentena no es un error del proceso: el lote queda apartado y las demás fuentes siguen.
    print(f"lotes en cuarentena en esta corrida: {cuarentenas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
