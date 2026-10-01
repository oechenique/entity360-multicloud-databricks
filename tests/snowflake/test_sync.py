"""Snowflake en el DAG: ENTITY360_SYNC, dueño de la base, refresca y reaplica grants sin ACCOUNTADMIN."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "snowflake"))
import integracion as I  # noqa: E402


def test_ceder_pasa_base_esquemas_y_tablas_conservando_grants():
    sql = I.sql_ceder()
    assert sql[0] == f"GRANT USAGE ON INTEGRATION {I.INTEGRACION} TO ROLE ENTITY360_SYNC"
    for objeto in (f"DATABASE {I.BASE}", f"ALL SCHEMAS IN DATABASE {I.BASE}", f"ALL ICEBERG TABLES IN DATABASE {I.BASE}"):
        assert f"GRANT OWNERSHIP ON {objeto} TO ROLE ENTITY360_SYNC COPY CURRENT GRANTS" in sql
    assert not any("ACCOUNTADMIN" in s or "MANAGE GRANTS" in s for s in sql)


def test_grants_del_dueno_sin_future_y_para_los_dos_roles():
    sql = I.sql_grants_dueno()
    assert sql and not any("FUTURE" in s for s in sql)       # FUTURE de base exige MANAGE GRANTS
    for rol in I.ROLES_LECTURA:
        assert f"GRANT SELECT ON ALL ICEBERG TABLES IN DATABASE {I.BASE} TO ROLE {rol}" in sql
    assert set(sql) < set(I.sql_grants())


def test_conexion_entorno_usa_sync_sin_roles_secundarios(monkeypatch):
    llamadas, ejecutado = {}, []

    class Con:
        def cursor(self):
            return types.SimpleNamespace(execute=ejecutado.append)

    conector = types.SimpleNamespace(connect=lambda **kw: llamadas.update(kw) or Con())
    monkeypatch.setitem(sys.modules, "snowflake", types.SimpleNamespace(connector=conector))
    monkeypatch.setitem(sys.modules, "snowflake.connector", conector)
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "ORG-CUENTA")
    monkeypatch.setenv("SNOWFLAKE_SYNC_USER", "ENTITY360_SYNC_SVC")
    monkeypatch.setenv("SNOWFLAKE_SYNC_KEY_PATH", "/k.p8")
    I.conectar("entorno")
    assert llamadas == {"account": "ORG-CUENTA", "user": "ENTITY360_SYNC_SVC", "private_key_file": "/k.p8",
                        "role": "ENTITY360_SYNC", "warehouse": "ENTITY360_WH"}
    assert ejecutado == ["USE SECONDARY ROLES NONE"]


def test_main_grants_ejecuta_solo_los_del_dueno(monkeypatch, capsys):
    ejecutados = []
    monkeypatch.setattr(I, "conectar", lambda c: types.SimpleNamespace(cursor=lambda: None, close=lambda: None))
    monkeypatch.setattr(I, "Ejecutor", lambda cur: ejecutados.append)
    monkeypatch.setattr(sys, "argv", ["integracion.py", "grants", "--conexion", "entorno"])
    assert I.main() == 0
    assert ejecutados == I.sql_grants_dueno()
