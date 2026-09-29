"""snowflake/cuenta.py en una carpeta temporal (SNOWFLAKE_HOME): claves, SQL de Snowsight y conexiones."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "snowflake"))
import cuenta as C  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_HOME", str(tmp_path))
    monkeypatch.setattr(C, "restringir", lambda ruta: None)   # icacls no hace falta en el test
    return tmp_path


def test_claves_no_imprime_privadas_y_no_pisa(home, capsys):
    C.claves()
    out = capsys.readouterr().out
    for quien in C.USUARIOS:
        pem = C.ruta_clave(quien).read_text()
        assert pem.startswith("-----BEGIN PRIVATE KEY-----")
        cuerpo = "".join(pem.strip().splitlines()[1:-1])
        assert cuerpo[:40] not in out and "PRIVATE KEY" not in out
    antes = C.ruta_clave("tf").read_bytes()
    C.claves()
    assert C.ruta_clave("tf").read_bytes() == antes and "ya existía" in capsys.readouterr().out


def test_sql_de_snowsight_solo_con_la_publica(home, capsys):
    C.claves()
    out = capsys.readouterr().out
    pub = C.publica(C.ruta_clave("tf"))
    assert f"RSA_PUBLIC_KEY = '{pub}'" in out and "CREATE USER IF NOT EXISTS ENTITY360_TF" in out
    assert "TYPE = SERVICE" in out and "PASSWORD" not in out.upper().replace("HAS_PASSWORD", "")
    assert f'dbt_rsa_public_key = "{C.publica(C.ruta_clave("dbt"))}"' in out


def test_conexiones_idempotentes_y_sin_pisar(home, capsys):
    C.claves()
    C.conexiones("miorg-micuenta", False)
    config = (home / "config").read_text()
    assert "organization_name = 'MIORG'" in config and "account_name = 'MICUENTA'" in config
    assert "BEGIN PRIVATE KEY" in config and "authenticator = 'SNOWFLAKE_JWT'" in config
    conexion = (home / "connections.toml").read_text()
    assert 'private_key_file = "' in conexion and "BEGIN PRIVATE KEY" not in conexion
    capsys.readouterr()
    C.conexiones("miorg-micuenta", False)
    assert capsys.readouterr().out.count("sin cambios") == 2
    with pytest.raises(SystemExit, match="otro contenido"):
        C.conexiones("otraorg-otracuenta", False)
    C.conexiones("otraorg-otracuenta", True)
    assert "OTRAORG" in (home / "config").read_text() and "MIORG" not in (home / "config").read_text()


def test_conserva_otras_secciones(home):
    (home / "connections.toml").write_text('[otra]\naccount = "X-Y"\n', encoding="utf-8")
    C.claves()
    C.conexiones("miorg-micuenta", False)
    texto = (home / "connections.toml").read_text()
    assert '[otra]\naccount = "X-Y"' in texto and "[entity360]" in texto


def test_cuenta_mal_escrita():
    with pytest.raises(SystemExit):
        C.cuenta_valida("sin-guion-de-mas-x y")
    assert C.cuenta_valida("abc123-xy_45") == ("ABC123", "XY_45")
