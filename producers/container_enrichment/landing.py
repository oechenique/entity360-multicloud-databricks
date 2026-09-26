"""Contrato de landing (regla 01) sobre el UC Volume, con la Files API de Databricks.

Auth (D4): OAuth M2M del SP entity360-producer-enrichment con DATABRICKS_HOST,
DATABRICKS_CLIENT_ID y DATABRICKS_CLIENT_SECRET (GitHub Secrets). Para pruebas manuales,
DATABRICKS_TOKEN (token de usuario de vida corta) en lugar del par client_id/secret.

Nada de esto imprime el host: los logs de GitHub Actions quedan visibles para quien lea el repo (principio 9).
"""

import hashlib
import json
import os
from datetime import datetime, timezone

import requests

RAIZ = "/Volumes/entity360/landing/raw"


class Volume:
    def __init__(self):
        self.host = os.environ["DATABRICKS_HOST"].rstrip("/")
        tk = os.environ.get("DATABRICKS_TOKEN")
        if not tk:
            r = requests.post(f"{self.host}/oidc/v1/token", timeout=60,
                              auth=(os.environ["DATABRICKS_CLIENT_ID"], os.environ["DATABRICKS_CLIENT_SECRET"]),
                              data={"grant_type": "client_credentials", "scope": "all-apis"})
            if not r.ok:
                raise RuntimeError(f"token OAuth M2M: HTTP {r.status_code} {r.text[:200]}")
            tk = r.json()["access_token"]
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {tk}"

    def _ok(self, r: requests.Response) -> requests.Response:
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code} {r.request.method} {r.url.split('/fs/')[-1]}: {r.text[:300]}")
        return r

    def put(self, ruta: str, contenido: bytes) -> None:
        self._ok(self.s.put(f"{self.host}/api/2.0/fs/files{ruta}", params={"overwrite": "false"},
                            headers={"Content-Type": "application/octet-stream"}, data=contenido, timeout=300))

    def get(self, ruta: str) -> bytes:
        return self._ok(self.s.get(f"{self.host}/api/2.0/fs/files{ruta}", timeout=120)).content

    def listar(self, ruta: str) -> list[dict]:
        r = self.s.get(f"{self.host}/api/2.0/fs/directories{ruta}", timeout=60)
        if r.status_code == 404:
            return []
        return self._ok(r).json().get("contents", [])

    def ultimo_manifest(self, fuente: str) -> dict | None:
        """El manifest más nuevo de la fuente (particiones y timestamps ordenan como texto)."""
        particiones = sorted(e["path"] for e in self.listar(f"{RAIZ}/{fuente}")
                             if e.get("is_directory") and "/ingest_date=" in e["path"])
        for p in reversed(particiones):
            manifests = sorted(e["path"] for e in self.listar(p) if e["path"].rsplit("/", 1)[1].startswith("_manifest_"))
            if manifests:
                return json.loads(self.get(manifests[-1]))
        return None


def jsonl(filas: list[dict]) -> bytes:
    """JSON Lines determinístico (D3): mismo contenido -> mismo sha256."""
    return "\n".join(json.dumps(f, ensure_ascii=False, sort_keys=True) for f in filas).encode("utf-8")


def publicar(vol: Volume | None, fuente: str, version: str, filas: list[dict], extra: dict) -> str:
    """Empuja un lote con su manifest. Sin cambios respecto del último manifest, no empuja (D6, capa 1)."""
    datos = jsonl(filas)
    sha = hashlib.sha256(datos).hexdigest()
    if vol is None:
        return f"solo lectura: {len(filas)} registros, {len(datos):,} bytes, sha256 {sha[:12]}"
    anterior = vol.ultimo_manifest(fuente)
    if anterior and anterior.get("sha256") == sha:
        return f"sin cambios (sha256 igual a {anterior['archivo']}): no se empuja nada"

    ahora = datetime.now(timezone.utc)
    ts = ahora.strftime("%Y%m%dT%H%M%SZ")
    carpeta = f"{RAIZ}/{fuente}/ingest_date={ahora:%Y-%m-%d}"
    archivo = f"{fuente}_{ts}.jsonl"
    manifest = {"fuente": fuente, "archivo": archivo, "registros": len(filas), "sha256": sha,
                "extraido_utc": ahora.isoformat(), "producer_version": version, **extra}
    vol.put(f"{carpeta}/{archivo}", datos)                                                   # 1. datos
    vol.put(f"{carpeta}/_manifest_{ts}.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))  # 2. manifest
    return f"PUT {carpeta}/{archivo} ({len(filas)} registros, {len(datos):,} bytes) + manifest"
