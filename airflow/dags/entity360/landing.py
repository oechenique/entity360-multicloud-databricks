"""Llegada de lotes al landing, para los sensores del DAG (regla 10): el último manifest de cada fuente.

Usa la Files API con el SP entity360-orquestador (DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET, ADR 0007).
Los umbrales de "fuente atrasada" salen de dbt/models/sources.yml (warn_after de la frescura de cada
fuente): la misma definición de atraso para el sensor y para dbt source freshness.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

RAW = "/Volumes/entity360/landing/raw"
FUENTES = ("sqlserver_cdc", "sec_edgar", "gdelt", "opensanctions", "wikidata")
UNIDADES = {"minute": "minutes", "hour": "hours", "day": "days"}
TS = re.compile(r"^_manifest_(\d{8}T\d{6}Z)\.json$")


def umbrales(sources_yml: Path) -> dict[str, timedelta]:
    """fuente -> warn_after de su frescura en dbt (source `landing`, tablas lotes_<fuente>)."""
    doc = yaml.safe_load(sources_yml.read_text(encoding="utf-8"))
    landing = next(s for s in doc["sources"] if s["name"] == "landing")
    out = {}
    for t in landing["tables"]:
        w = t["config"]["freshness"]["warn_after"]
        out[t["name"].removeprefix("lotes_")] = timedelta(**{UNIDADES[w["period"]]: w["count"]})
    return out


def ts_de(nombre: str) -> datetime | None:
    m = TS.match(nombre)
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if m else None


def ultimo(nombres: list[str]) -> datetime | None:
    """El timestamp del manifest más reciente entre nombres de archivos (None si no hay)."""
    return max((t for t in map(ts_de, nombres) if t), default=None)


class Landing:
    def __init__(self):
        self.host = os.environ["DATABRICKS_HOST"].rstrip("/")
        if not self.host.startswith("https://"):
            self.host = "https://" + self.host
        r = requests.post(f"{self.host}/oidc/v1/token", timeout=60,
                          auth=(os.environ["DATABRICKS_CLIENT_ID"], os.environ["DATABRICKS_CLIENT_SECRET"]),
                          data={"grant_type": "client_credentials", "scope": "all-apis"})
        r.raise_for_status()
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def listar(self, ruta: str) -> list[dict]:
        out, token = [], None
        while True:
            r = self.s.get(f"{self.host}/api/2.0/fs/directories{ruta}", timeout=60,
                           params={"page_token": token} if token else None)
            if r.status_code == 404:
                return []
            r.raise_for_status()
            d = r.json()
            out += d.get("contents", [])
            token = d.get("next_page_token")
            if not token:
                return out

    def ultimo_manifest(self, fuente: str) -> datetime | None:
        """Mira las dos particiones ingest_date más recientes (un lote de las 23:59 cae en la anterior)."""
        dias = sorted((e["name"] for e in self.listar(f"{RAW}/{fuente}") if e.get("is_directory")), reverse=True)
        return ultimo([e["name"] for d in dias[:2] for e in self.listar(f"{RAW}/{fuente}/{d}")])
