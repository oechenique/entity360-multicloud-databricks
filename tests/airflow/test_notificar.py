"""Aviso de cierre de la corrida (notificar.py) y credenciales de Telegram del llavero."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "airflow" / "dags"))
from entity360 import notificar  # noqa: E402

FIN = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)


def test_mensaje_ok():
    titulo, texto = notificar.mensaje("ok", "entity360_convergencia", "manual__x", FIN - timedelta(minutes=36), ahora=FIN)
    assert titulo == "entity360: corrida OK"
    assert "manual__x (36 min)" in texto and "Snowflake" in texto


def test_mensaje_falla_lista_las_tareas():
    titulo, texto = notificar.mensaje("falla", "d", "r", FIN - timedelta(minutes=95), ["dbt_marts", "contratos"], FIN)
    assert titulo == "entity360: corrida FALLIDA"
    assert "(1 h 35 min)" in texto and "Fallaron: contratos, dbt_marts" in texto


def test_mensaje_falla_sin_lista_ni_inicio():
    _, texto = notificar.mensaje("falla", "d", "r", None, None, FIN)
    assert "(-)" in texto and "ver la UI de Airflow" in texto


def test_telegram_del_llavero_solo_con_las_dos_claves(monkeypatch):
    import importlib.util                 # por ruta: hay otros credenciales.py (productores) en sys.path
    spec = importlib.util.spec_from_file_location("airflow_credenciales", RAIZ / "airflow" / "credenciales.py")
    credenciales = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(credenciales)
    llavero = {("entity360-telegram", "bot_token"): "tk", ("entity360-telegram", "chat_id"): "42"}
    monkeypatch.setattr(credenciales.keyring, "get_password", lambda s, k: llavero.get((s, k)))
    assert credenciales.telegram() == {"TELEGRAM_BOT_TOKEN": "tk", "TELEGRAM_CHAT_ID": "42"}
    del llavero[("entity360-telegram", "chat_id")]
    assert credenciales.telegram() == {}
