"""Sensores de llegada del DAG de convergencia (regla 10): partes puras de airflow/dags/entity360/landing.py."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "airflow" / "dags"))
from entity360 import landing  # noqa: E402


def test_umbrales_salen_de_la_frescura_de_dbt():
    u = landing.umbrales(RAIZ / "dbt" / "models" / "sources.yml")
    assert set(u) == set(landing.FUENTES)
    assert u["gdelt"] == timedelta(hours=12)
    assert u["opensanctions"] == timedelta(hours=36)
    assert u["sec_edgar"] == timedelta(days=10)


def test_ts_de_manifest():
    assert landing.ts_de("_manifest_20260927T201512Z.json") == datetime(2026, 9, 27, 20, 15, 12, tzinfo=timezone.utc)
    assert landing.ts_de("gdelt_20260927T201512Z.jsonl") is None
    assert landing.ts_de("_contrato_20260927T201512Z.json") is None


def test_ultimo_ignora_datos_y_veredictos():
    nombres = ["_manifest_20260927T121342Z.json", "gdelt_20260927T201512Z.jsonl", "_contrato_20260928T000000Z.json",
               "_manifest_20260927T201512Z.json"]
    assert landing.ultimo(nombres) == datetime(2026, 9, 27, 20, 15, 12, tzinfo=timezone.utc)
    assert landing.ultimo(["gdelt_x.jsonl"]) is None
