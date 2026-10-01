"""Manifest de latido (Pendiente 8): una corrida sin datos nuevos deja un manifest sin archivo, para que el
sensor del DAG mida si el productor está vivo. Sin nube: el volume, S3 y la Files API son dobles."""

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PROD = RAIZ / "producers"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")   # boto3.client() al importar los módulos de AWS
sys.path.insert(0, str(PROD / "container_enrichment"))
sys.path.insert(0, str(RAIZ / "airflow" / "dags"))

import landing                                          # noqa: E402
from entity360 import landing as sensor                 # noqa: E402


def cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cdc = cargar("cdc_extractor", PROD / "cdc_extractor" / "extractor.py")
sec = cargar("sec_extractor", PROD / "aws_sec_edgar" / "extractor.py")
entrega = cargar("sec_entrega", PROD / "aws_sec_edgar" / "entrega.py")
AHORA = datetime(2026, 10, 1, 11, 45, tzinfo=timezone.utc)


class Volumen:
    def __init__(self):
        self.archivos: dict[str, bytes] = {}

    def put(self, ruta, contenido):
        self.archivos[ruta] = contenido

    def manifests(self):
        return [json.loads(v) for r, v in sorted(self.archivos.items()) if "/_manifest_" in r]

    def ultimo_manifest(self, fuente=None):
        m = self.manifests()
        return m[-1] if m else None


class Reloj(datetime):
    """Cada now() avanza una hora: corridas distintas, manifests distintos."""
    n = 0

    @classmethod
    def now(cls, tz=None):
        cls.n += 1
        return AHORA.replace(hour=cls.n % 24)


def test_enriquecimiento_sin_cambios_deja_latido_con_el_mismo_sha(monkeypatch):
    monkeypatch.setattr(landing, "datetime", Reloj)
    vol, filas = Volumen(), [{"id": 1}, {"id": 2}]
    landing.publicar(vol, "wikidata", "v1", filas, {})
    r = landing.publicar(vol, "wikidata", "v1", filas, {})
    lote, latido = vol.manifests()
    assert "latido" in r
    assert latido["sin_cambios"] and latido["archivo"] is None and latido["registros"] == 0
    assert latido["sha256"] == lote["sha256"] and latido["ultimo_archivo"] == lote["archivo"]
    assert sum(1 for r in vol.archivos if r.endswith(".jsonl")) == 1     # Bronze no ve nada nuevo
    # El latido sigue deduplicando: la tercera corrida igual tampoco empuja datos.
    landing.publicar(vol, "wikidata", "v1", filas, {})
    assert sum(1 for r in vol.archivos if r.endswith(".jsonl")) == 1
    assert vol.manifests()[-1]["ultimo_archivo"] == lote["archivo"]


def test_cdc_latido_conserva_el_lsn():
    anterior = {"fuente": "sqlserver_cdc", "archivo": "sqlserver_cdc_x.jsonl", "sha256": "abc",
                "lsn_desde": "0x01", "lsn_hasta": "0x0A", "por_tabla": {"t": 3}}
    m = cdc.manifest_latido(anterior, "0x0A", AHORA)
    assert m["sin_cambios"] and m["archivo"] is None and m["registros"] == 0
    assert (m["lsn_desde"], m["lsn_hasta"], m["sha256"]) == ("0x0A", "0x0A", "abc")
    assert m["ultimo_archivo"] == "sqlserver_cdc_x.jsonl" and m["por_tabla"] == {}
    assert m["extraido_utc"] == AHORA.isoformat()


def test_cdc_latido_escribe_en_la_particion_del_dia():
    vol = Volumen()
    ruta = cdc.latido(vol, "0x0A")
    assert ruta.startswith(f"{cdc.RAIZ_VOLUME}/ingest_date=") and "/_manifest_" in ruta
    assert vol.manifests()[0]["lsn_hasta"] == "0x0A"


def test_sec_latido_y_entrega_sube_solo_el_manifest(monkeypatch):
    m = sec.manifest_latido(AHORA)
    assert m["sin_cambios"] and m["archivo"] is None and m["registros"] == 0
    clave = "lotes/ingest_date=2026-10-01/_manifest_20261001T114500Z.json"

    class S3:
        def get_object(self, Bucket, Key):
            assert Key == clave, "la entrega de un latido no busca archivo de datos"
            return {"Body": type("B", (), {"read": lambda self: json.dumps(m).encode()})()}

    subidos = []
    monkeypatch.setattr(entrega, "s3", S3())
    monkeypatch.setattr(entrega, "secrets", type("S", (), {
        "get_secret_value": lambda self, SecretId: {"SecretString": json.dumps({"host": "https://h"})}})())
    monkeypatch.setattr(entrega, "token", lambda cred: "tk")
    monkeypatch.setattr(entrega, "subir", lambda host, tk, ruta, contenido: subidos.append(ruta) or "201")
    monkeypatch.setenv("SECRET_ID", "x")
    monkeypatch.setenv("VOLUME_ROOT", "/Volumes/entity360/landing/raw")
    r = entrega.lambda_handler({"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": clave}}}]}, None)
    assert subidos == ["/Volumes/entity360/landing/raw/sec_edgar/ingest_date=2026-10-01/_manifest_20261001T114500Z.json"]
    assert r[0]["latido"] == clave


def test_el_sensor_cuenta_el_latido():
    assert sensor.ultimo(["sqlserver_cdc_20260926T100000Z.jsonl", "_manifest_20260926T100000Z.json",
                          "_contrato_20260926T100000Z.json", "_manifest_20261001T114500Z.json"]) == AHORA
