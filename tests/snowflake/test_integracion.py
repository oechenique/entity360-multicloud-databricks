"""snowflake/integracion.py (fase 9, ADR 0012) con un cursor falso: sin Snowflake, sin trial.

Lo que se prueba: que no toque nada si la integración y la base ya existen, que cree solo lo que falta,
que no cambie una integración con otra configuración, y que el secreto del SP nunca aparezca en lo que
el script imprime, loguea o propaga como error.
"""

import logging
import sys
import traceback
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "snowflake"))
import integracion as I  # noqa: E402

SECRETO = "dose-S3cr3t'con\\raros-0123456789"
CFG = I.Config("https://<WORKSPACE_URL>", "11111111-2222-3333-4444-555555555555", "A")
MUTANTES = ("CREATE", "ALTER", "DROP", "GRANT", "REVOKE")


class Cursor:
    """Responde por prefijo del SQL y registra todo lo ejecutado."""

    def __init__(self, respuestas: dict[str, list], falla_en: str | None = None):
        self.respuestas, self.falla_en, self.ejecutadas, self._ult = respuestas, falla_en, [], []

    def execute(self, sql):
        self.ejecutadas.append(sql)
        if self.falla_en and sql.startswith(self.falla_en):
            # Peor caso de un error de Snowflake: cita el statement entero, con el secreto adentro.
            raise Exception(f"001003 (42000): SQL compilation error: syntax error line 1 in '{sql}'")
        self._ult = next((v for k, v in self.respuestas.items() if sql.startswith(k)), [])

    def fetchall(self):
        return self._ult


def desc(cfg=CFG, modo=None):
    return [("CATALOG_SOURCE", "String", "ICEBERG_REST", ""),
            ("REST_CONFIG", "Object", f"CATALOG_URI={cfg.catalog_uri},CATALOG_NAME=entity360,"
                                      f"ACCESS_DELEGATION_MODE={modo or cfg.modo}", ""),
            ("REST_AUTHENTICATION", "Object", f"TYPE=OAUTH,OAUTH_CLIENT_ID={cfg.client_id},OAUTH_CLIENT_SECRET=****", "")]


EXISTE = {"SHOW CATALOG INTEGRATIONS": [("ENTITY360_UNITY",)], "DESC CATALOG INTEGRATION": desc(),
          "SHOW DATABASES": [("ENTITY360_UC",)], "SELECT SYSTEM$VERIFY": [('{"success": true}',)]}
NADA = {"SELECT SYSTEM$VERIFY": [('{"success": true}',)]}


def mutantes(cursor):
    return [s for s in cursor.ejecutadas if s.split()[0] in MUTANTES]


def sin_secreto(*textos):
    for t in textos:
        assert SECRETO not in t and I._escapar(SECRETO) not in t


# ------------------------------------------------------------------ idempotencia

def test_si_ya_existe_no_toca_nada():
    c = Cursor(EXISTE)
    hecho = I.crear(I.Ejecutor(c), CFG, SECRETO, decir=lambda _: None)
    assert mutantes(c) == []
    assert [s.split()[0] for s in c.ejecutadas] == ["SHOW", "DESC", "SHOW", "SELECT"]
    assert any("sin cambios" in h for h in hecho)


def test_si_no_existe_crea_integracion_base_y_grants():
    c = Cursor(NADA)
    I.crear(I.Ejecutor(c), CFG, SECRETO, decir=lambda _: None)
    creadas = mutantes(c)
    assert creadas[0].startswith("CREATE CATALOG INTEGRATION IF NOT EXISTS ENTITY360_UNITY")
    assert "ACCESS_DELEGATION_MODE = VENDED_CREDENTIALS" in creadas[0]
    assert creadas[1].startswith("CREATE DATABASE IF NOT EXISTS ENTITY360_UC LINKED_CATALOG")
    assert "ALLOWED_NAMESPACES = ('gold')" in creadas[1] and "REFRESH_INTERVAL_SECONDS = 3600" in creadas[0]
    assert "ALLOWED_WRITE_OPERATIONS = NONE" in creadas[1] and "SYNC_INTERVAL_SECONDS = 3600" in creadas[1]
    assert all(s.startswith("GRANT") for s in creadas[2:]) and len(creadas[2:]) == len(I.sql_grants())
    assert not any(s.startswith(("DROP", "ALTER")) for s in c.ejecutadas)


def test_integracion_existente_y_base_nueva_crea_solo_la_base():
    c = Cursor({**EXISTE, "SHOW DATABASES": []})
    I.crear(I.Ejecutor(c), CFG, SECRETO, decir=lambda _: None)
    assert not any("CATALOG INTEGRATION" in s for s in mutantes(c))
    assert mutantes(c)[0].startswith("CREATE DATABASE IF NOT EXISTS")


def test_otra_configuracion_falla_sin_cambiar_nada():
    c = Cursor({**EXISTE, "DESC CATALOG INTEGRATION": desc(modo="EXTERNAL_VOLUME_CREDENTIALS")})
    with pytest.raises(I.IntegracionDesalineada, match="ACCESS_DELEGATION_MODE"):
        I.crear(I.Ejecutor(c), CFG, SECRETO, decir=lambda _: None)
    assert mutantes(c) == []


def test_rotar_secreto_es_solo_un_alter():
    c = Cursor(EXISTE)
    I.crear(I.Ejecutor(c), CFG, SECRETO, rotar=True, decir=lambda _: None)
    assert [s.split()[0] for s in mutantes(c)] == ["ALTER"]
    assert mutantes(c)[0].startswith("ALTER CATALOG INTEGRATION ENTITY360_UNITY SET REST_AUTHENTICATION")


def test_camino_a2_usa_el_external_volume():
    cfg = I.Config(CFG.host, CFG.client_id, "A2", "ENTITY360_GOLD_VOL")
    assert "ACCESS_DELEGATION_MODE = EXTERNAL_VOLUME_CREDENTIALS" in I.sql_crear_integracion(cfg, SECRETO)
    base = I.sql_crear_base(cfg)
    assert "EXTERNAL_VOLUME = 'ENTITY360_GOLD_VOL'" in base
    assert base.index("EXTERNAL_VOLUME") > base.index("SYNC_INTERVAL_SECONDS = 3600)")   # fuera de LINKED_CATALOG
    with pytest.raises(ValueError):
        I.Config(CFG.host, CFG.client_id, "A2")
    with pytest.raises(ValueError):
        I.Config(CFG.host, CFG.client_id, "B")


# ------------------------------------------------------------------ el secreto no sale

@pytest.mark.parametrize("escenario", ["crear", "rotar", "ya_existe", "desalineada"])
def test_el_secreto_no_aparece_en_la_salida(escenario, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    respuestas = {"crear": NADA, "rotar": EXISTE, "ya_existe": EXISTE,
                  "desalineada": {**EXISTE, "DESC CATALOG INTEGRATION": desc(modo="OTRO")}}[escenario]
    c = Cursor(respuestas)
    hecho, error = [], ""
    try:
        hecho = I.crear(I.Ejecutor(c), CFG, SECRETO, rotar=escenario == "rotar")
    except I.IntegracionDesalineada as e:
        error = "".join(traceback.format_exception(e))
    salida = capsys.readouterr()
    sin_secreto(salida.out, salida.err, caplog.text, repr(hecho), error)
    if escenario in ("crear", "rotar"):
        assert any(SECRETO in s or I._escapar(SECRETO) in s for s in c.ejecutadas)   # sí llegó a Snowflake


@pytest.mark.parametrize("falla_en", ["CREATE CATALOG INTEGRATION", "ALTER CATALOG INTEGRATION"])
def test_un_error_del_conector_sale_sin_el_secreto(falla_en, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    c = Cursor(EXISTE if falla_en.startswith("ALTER") else NADA, falla_en=falla_en)
    with pytest.raises(RuntimeError) as e:
        I.crear(I.Ejecutor(c), CFG, SECRETO, rotar=True)
    salida = capsys.readouterr()
    assert I.OCULTO in str(e.value)
    sin_secreto(str(e.value), "".join(traceback.format_exception(e.value)), salida.out, salida.err, caplog.text)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_ocultar_tapa_el_secreto_tal_cual_y_escapado():
    assert I.ocultar(f"a {SECRETO} b {I._escapar(SECRETO)}", SECRETO) == f"a {I.OCULTO} b {I.OCULTO}"
    assert I.ocultar("sin nada", None) == "sin nada"


def test_simular_solo_lee_y_lista_lo_demas_sin_el_secreto(capsys):
    c = Cursor(NADA)
    sim = I.Simulador(c)
    I.crear(sim, CFG, SECRETO, decir=lambda _: None)
    assert all(s.split()[0] in ("SHOW", "DESC") for s in c.ejecutadas)      # a Snowflake solo llegó lectura
    assert sim.pendientes[0].startswith("CREATE CATALOG INTEGRATION IF NOT EXISTS")
    assert any(p.startswith("CREATE DATABASE IF NOT EXISTS ENTITY360_UC") for p in sim.pendientes)
    sin_secreto(*sim.pendientes, capsys.readouterr().out)
    assert any(I.OCULTO in p for p in sim.pendientes)


def test_refrescar_cada_tabla_de_la_base():
    tablas = [("2026-09-29", "dim_entity", "ENTITY360_UC", "gold"), ("2026-09-29", "fct_news_signal", "ENTITY360_UC", "gold")]
    c = Cursor({"SHOW ICEBERG TABLES": tablas, "ALTER ICEBERG TABLE": [("refrescada",)]})
    salida = I.refrescar(I.Ejecutor(c), decir=lambda _: None)
    assert c.ejecutadas[1:] == ['ALTER ICEBERG TABLE ENTITY360_UC."gold"."dim_entity" REFRESH',
                                'ALTER ICEBERG TABLE ENTITY360_UC."gold"."fct_news_signal" REFRESH']
    assert salida == ["gold.dim_entity: refrescada", "gold.fct_news_signal: refrescada"]
