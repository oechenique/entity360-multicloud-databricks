"""snowflake/validar_vending.py con HTTP y PyIceberg simulados.

El 2026-09-29 el paso 1 imprimió el token OAuth del SP (Pasos imprimía lo que devolvía cada paso). Este
test corre main() entero y exige que ni el token ni el secreto aparezcan en la salida, también cuando un
paso falla con un mensaje que los contiene.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "snowflake"))
import validar_vending as V  # noqa: E402

TOKEN = "eyJ-token-de-prueba.que-no-puede-salir"
SECRETO = "dose-secreto-de-prueba"


class Resp:
    def __init__(self, status, cuerpo=None, texto=""):
        self.status_code, self._cuerpo, self.text = status, cuerpo or {}, texto or str(cuerpo)
        self.ok = status < 400

    def json(self):
        return self._cuerpo

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


def entorno(monkeypatch, silver_status=403, config_eco=False, filas=1136):
    monkeypatch.setenv("DATABRICKS_HOST", "https://<WORKSPACE_URL>")
    monkeypatch.setenv("AWS_CONFIG_FILE", "NUL")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "NUL")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(V, "credenciales_sp", lambda: ("client-id", SECRETO))
    monkeypatch.setattr(V.requests, "post", lambda *a, **k: Resp(
        200, {"access_token": TOKEN, "scope": "all-apis", "expires_in": 3600}))

    def get(url, **k):
        if url.endswith("/v1/config"):
            # Peor caso: un endpoint que devuelve el token en el cuerpo (un error de proxy, un eco).
            return Resp(500 if config_eco else 200, {"defaults": {}},
                        texto=f"eco {k['headers']['Authorization']}" if config_eco else "{}")
        if "/namespaces/silver/" in url:
            return Resp(silver_status, {})
        return Resp(200, {"config": {"s3.access-key-id": "x", "s3.session-token": "y"}})
    monkeypatch.setattr(V.requests, "get", get)

    class Tabla:
        def scan(self, **k):
            return types.SimpleNamespace(to_arrow=lambda: types.SimpleNamespace(num_rows=filas))

        def current_snapshot(self):
            return types.SimpleNamespace(snapshot_id=1)

    rest = types.ModuleType("pyiceberg.catalog.rest")
    rest.RestCatalog = lambda *a, **k: types.SimpleNamespace(load_table=lambda n: Tabla())
    monkeypatch.setitem(sys.modules, "pyiceberg.catalog.rest", rest)
    monkeypatch.setattr(sys, "argv", ["validar_vending.py", "--filas-esperadas", "1136"])


@pytest.mark.parametrize("caso", ["todo_ok", "silver_visible", "error_con_eco", "conteo_distinto"])
def test_ni_el_token_ni_el_secreto_aparecen(caso, monkeypatch, capsys):
    entorno(monkeypatch, silver_status=200 if caso == "silver_visible" else 403,
            config_eco=caso == "error_con_eco", filas=1000 if caso == "conteo_distinto" else 1136)
    codigo = V.main()
    salida = capsys.readouterr()
    for texto in (salida.out, salida.err):
        assert TOKEN not in texto and SECRETO not in texto
    assert codigo == (0 if caso == "todo_ok" else 1)
    if caso == "error_con_eco":
        assert "***" in salida.out


def test_todo_ok_reporta_los_cinco_pasos(monkeypatch, capsys):
    entorno(monkeypatch)
    assert V.main() == 0
    out = capsys.readouterr().out
    assert out.count("\nOK:") == 5 and "vence en 3600 s" in out and "Camino A habilitado" in out
