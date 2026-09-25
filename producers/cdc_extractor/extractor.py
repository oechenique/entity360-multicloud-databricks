"""Extractor CDC (regla 04): SQL Server legacy -> UC Volume, con el contrato de landing.

Cada corrida:
1. Rango de LSN: desde el siguiente al último procesado (checkpoint) hasta fn_cdc_get_max_lsn().
   - Checkpoint en state/checkpoint.json (fuera de git).
   - Si el archivo no está: se recupera del lsn_hasta del último _manifest_<ts>.json del volume.
   - Si tampoco hay manifests: primera corrida, desde el mínimo LSN de cada instancia.
   - Si el cleanup de CDC ya borró cambios posteriores al checkpoint, corta con error (no hay
     forma de recuperarlos desde el CDC; hace falta una recarga).
2. Lee cdc.fn_cdc_get_all_changes_erp_<tabla> de las 4 instancias.
3. Sin cambios: no empuja nada (capa 1 de idempotencia, D6).
4. Con cambios: PUT del .jsonl y después del _manifest_<ts>.json con OAuth M2M del SP, y recién al
   final guarda el checkpoint. Si se corta en el medio, la corrida siguiente re-emite el mismo rango
   (mismo contenido y sha256) y Bronze lo descarta (capa 2).

Credenciales en el Administrador de credenciales de Windows (credenciales.py), nunca a disco.

Uso:
    .venv\\Scripts\\python.exe producers\\cdc_extractor\\extractor.py [--solo-leer]
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import keyring
import pymssql
import requests

VERSION = "cdc-extractor-1.0"
SERVICIO = "entity360-cdc-extractor"
FUENTE = "sqlserver_cdc"
RAIZ_VOLUME = f"/Volumes/entity360/landing/raw/{FUENTE}"
INSTANCIAS = ["erp_entidad", "erp_direccion", "erp_nombre_alternativo", "erp_relacion"]
OPERACION = {1: "delete", 2: "insert", 3: "update_antes", 4: "update"}
CHECKPOINT = Path(__file__).resolve().parent / "state" / "checkpoint.json"


def lsn_hex(b: bytes) -> str:
    return "0x" + b.hex().upper()


def lsn_bytes(h: str) -> bytes:
    return bytes.fromhex(h[2:])


# --------------------------------------------------------------------------- Databricks

class Volume:
    def __init__(self):
        self.host = keyring.get_password(SERVICIO, "databricks_host").rstrip("/")
        r = requests.post(f"{self.host}/oidc/v1/token", timeout=60,
                          auth=(keyring.get_password(SERVICIO, "databricks_client_id"),
                                keyring.get_password(SERVICIO, "databricks_secret")),
                          data={"grant_type": "client_credentials", "scope": "all-apis"})
        r.raise_for_status()
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def _ok(self, r: requests.Response) -> requests.Response:
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code} {r.request.method} {r.url.split('/fs/')[-1]}: {r.text[:300]}")
        return r

    def put(self, ruta: str, contenido: bytes) -> None:
        self._ok(self.s.put(f"{self.host}/api/2.0/fs/files{ruta}", params={"overwrite": "false"},
                            headers={"Content-Type": "application/octet-stream"}, data=contenido, timeout=120))

    def get(self, ruta: str) -> bytes:
        return self._ok(self.s.get(f"{self.host}/api/2.0/fs/files{ruta}", timeout=120)).content

    def listar(self, ruta: str) -> list[dict]:
        r = self.s.get(f"{self.host}/api/2.0/fs/directories{ruta}", timeout=60)
        if r.status_code == 404:
            return []
        return self._ok(r).json().get("contents", [])

    def ultimo_manifest(self) -> dict | None:
        """Último manifest del volume (por nombre: ingest_date y timestamp ordenan cronológicamente)."""
        particiones = sorted(e["path"] for e in self.listar(RAIZ_VOLUME) if e.get("is_directory"))
        for p in reversed(particiones):
            manifests = sorted(e["path"] for e in self.listar(p) if e["name"].startswith("_manifest_"))
            if manifests:
                return json.loads(self.get(manifests[-1]))
        return None


# --------------------------------------------------------------------------- checkpoint

def leer_checkpoint(vol: Volume | None) -> tuple[str | None, str]:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))["lsn_hasta"], "archivo local"
    if vol is not None:
        m = vol.ultimo_manifest()
        if m:
            return m["lsn_hasta"], f"recuperado del manifest {m['archivo']}"
    return None, "sin checkpoint (primera corrida)"


def guardar_checkpoint(manifest: dict, ruta_manifest: str) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps({"lsn_hasta": manifest["lsn_hasta"], "manifest": ruta_manifest,
                                      "guardado_utc": datetime.now(timezone.utc).isoformat()}, indent=2),
                          encoding="utf-8")


# --------------------------------------------------------------------------- SQL Server

def leer_cambios(cur, desde_ckpt: str | None) -> tuple[list[dict], str | None, str | None]:
    cur.execute("SELECT sys.fn_cdc_get_max_lsn()")
    hasta = cur.fetchone()[0]
    filas, desde_global = [], None
    for inst in INSTANCIAS:
        cur.execute("SELECT sys.fn_cdc_get_min_lsn(%s)", (inst,))
        minimo = cur.fetchone()[0]
        if desde_ckpt is None:
            desde = minimo
        else:
            cur.execute("SELECT sys.fn_cdc_increment_lsn(%s)", (lsn_bytes(desde_ckpt),))
            desde = cur.fetchone()[0]
            if desde < minimo:
                raise RuntimeError(f"{inst}: el cleanup de CDC borró cambios posteriores al checkpoint "
                                   f"({desde_ckpt} < mínimo {lsn_hex(minimo)}). Hace falta una recarga.")
        if desde > hasta:
            continue
        desde_global = min(desde_global or desde, desde)
        cur.execute(f"""
            SELECT sys.fn_cdc_map_lsn_to_time(__$start_lsn) AS commit_time, *
            FROM cdc.fn_cdc_get_all_changes_{inst}(%s, %s, N'all')
            ORDER BY __$start_lsn, __$seqval""", (desde, hasta))
        cols = [c[0] for c in cur.description]
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            filas.append({
                "tabla": inst.removeprefix("erp_"),
                "op": OPERACION[d["__$operation"]],
                "lsn": lsn_hex(d["__$start_lsn"]),
                "seqval": lsn_hex(d["__$seqval"]),
                "commit_time": d["commit_time"],
                "datos": {k: v for k, v in d.items() if not k.startswith("__$") and k != "commit_time"},
            })
    return filas, (lsn_hex(desde_global) if desde_global else None), lsn_hex(hasta) if hasta else None


def serializar(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-leer", action="store_true", help="lee y resume, no empuja ni guarda checkpoint")
    a = ap.parse_args()
    t0 = time.perf_counter()

    vol = None if a.solo_leer else Volume()
    desde_ckpt, origen = leer_checkpoint(vol)
    print(f"checkpoint: {desde_ckpt or '-'} ({origen})")

    con = pymssql.connect(server="127.0.0.1", port=1433, user="cdc_extractor",
                          password=keyring.get_password(SERVICIO, "sql_password"), database="entity360_erp")
    filas, lsn_desde, lsn_hasta = leer_cambios(con.cursor(), desde_ckpt)
    con.close()

    por_tabla, por_op = {}, {}
    for f in filas:
        por_tabla[f["tabla"]] = por_tabla.get(f["tabla"], 0) + 1
        por_op[f["op"]] = por_op.get(f["op"], 0) + 1
    print(f"cambios: {len(filas)} | por tabla: {por_tabla} | por operación: {por_op} | rango {lsn_desde} -> {lsn_hasta}")
    if not filas:
        print("sin cambios nuevos: no se empuja nada (idempotente).")
        if desde_ckpt and not CHECKPOINT.exists() and not a.solo_leer:
            # Recuperado del volume: se vuelve a dejar el archivo local.
            guardar_checkpoint({"lsn_hasta": desde_ckpt}, origen)
            print(f"checkpoint local restaurado -> {desde_ckpt}")
        return 0
    if a.solo_leer:
        return 0

    ahora = datetime.now(timezone.utc)
    ts = ahora.strftime("%Y%m%dT%H%M%SZ")
    carpeta = f"{RAIZ_VOLUME}/ingest_date={ahora:%Y-%m-%d}"
    datos = "\n".join(json.dumps(f, ensure_ascii=False, default=serializar) for f in filas).encode("utf-8")
    ruta_datos = f"{carpeta}/{FUENTE}_{ts}.jsonl"
    manifest = {
        "fuente": FUENTE, "archivo": ruta_datos.rsplit("/", 1)[1], "registros": len(filas),
        "sha256": hashlib.sha256(datos).hexdigest(), "extraido_utc": ahora.isoformat(),
        "producer_version": VERSION, "lsn_desde": lsn_desde, "lsn_hasta": lsn_hasta,
        "por_tabla": por_tabla, "por_operacion": por_op,
    }
    ruta_manifest = f"{carpeta}/_manifest_{ts}.json"
    vol.put(ruta_datos, datos)                                               # 1. datos
    vol.put(ruta_manifest, json.dumps(manifest, indent=2).encode("utf-8"))   # 2. manifest
    guardar_checkpoint(manifest, ruta_manifest)                              # 3. checkpoint
    print(f"PUT {ruta_datos} ({len(datos):,} bytes) + manifest; checkpoint -> {lsn_hasta} "
          f"({time.perf_counter() - t0:,.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
