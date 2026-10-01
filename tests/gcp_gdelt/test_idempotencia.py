"""Idempotencia del productor GDELT (regla 06): por GKGRECORDID en la consulta y por el último
manifest en el push. Sin nube: BigQuery y el volume son dobles en memoria.

El doble de BigQuery aplica las dos condiciones SQL que importan (NOT IN del respaldo en la ventana,
y lote_utc > @hasta), así que lo que se prueba es el circuito del extractor: qué consulta arma según
exista el respaldo, qué respalda, qué empuja y de dónde retoma. `landing` es el real, sobre un
volume en memoria que, como la Files API con overwrite=false, no pisa archivos.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound

import extractor
import landing


class Reloj(datetime):
    """datetime.now() controlado, en extractor y en landing."""
    actual: datetime

    @classmethod
    def now(cls, tz=None):
        return cls.actual


def hora(h: int, m: int = 23) -> Reloj:
    return Reloj(2026, 9, 26, h, m, tzinfo=timezone.utc)


def mencion(gkg_id: str, entidad: str, h: int) -> dict:
    return {"gkg_record_id": gkg_id, "fecha_gdelt": hora(h, 0), "medio": "example.com",
            "url": f"https://example.com/{gkg_id}", "entidad": entidad,
            "formas": ["bank galicia"], "tono": -1.5}


def param(cfg, nombre):
    return next(p.value for p in cfg.query_parameters if p.name == nombre)


def ts(v) -> datetime:
    return v if isinstance(v, datetime) else Reloj.fromisoformat(v)


class FakeBigQuery:
    def __init__(self):
        self.gkg: list[dict] = []        # lo que devuelve la consulta de GKG antes de excluir el respaldo
        self.respaldo: list[dict] = []
        self.existe = False
        self.consultas: list[str] = []
        self.dry_run_bytes = 60 * 2**20

    def get_table(self, tabla):
        if not self.existe:
            raise NotFound(tabla)

    def query(self, sql, job_config):
        self.consultas.append(sql)
        if job_config.dry_run:
            return SimpleNamespace(total_bytes_processed=self.dry_run_bytes)
        if "gkg_partitioned" in sql:
            filas = list(self.gkg)
            if "NOT IN (SELECT gkg_record_id" in sql:
                desde = param(job_config, "desde") - timedelta(days=1)
                vistos = {r["gkg_record_id"] for r in self.respaldo
                          if Reloj.fromisoformat(r["lote_utc"]) >= desde}
                filas = [f for f in filas if f["gkg_record_id"] not in vistos]
        else:
            assert sql.startswith("SELECT * FROM")
            hasta = next((p.value for p in job_config.query_parameters if p.name == "hasta"), None)
            filas = [{**r, "lote_utc": Reloj.fromisoformat(r["lote_utc"])} for r in self.respaldo
                     if hasta is None or ts(r["lote_utc"]) > ts(hasta)]
        return SimpleNamespace(result=lambda: filas, total_bytes_billed=10 * 2**20)

    def load_table_from_json(self, datos, tabla, job_config):
        assert job_config.write_disposition == "WRITE_APPEND"
        self.respaldo += datos
        self.existe = True
        return SimpleNamespace(result=lambda: None)


class FakeVolume:
    def __init__(self):
        self.archivos: dict[str, bytes] = {}
        self.falla_put = False

    def put(self, ruta, contenido):
        if self.falla_put:
            raise RuntimeError("HTTP 503 PUT")
        assert ruta not in self.archivos, f"overwrite=false: {ruta}"
        self.archivos[ruta] = contenido

    def get(self, ruta):
        return self.archivos[ruta]

    def listar(self, ruta):
        hijos = {}
        for r in self.archivos:
            if r.startswith(ruta + "/"):
                resto = r[len(ruta) + 1:]
                nombre = resto.split("/", 1)[0]
                hijos[f"{ruta}/{nombre}"] = "/" in resto
        return [{"path": p, "is_directory": d} for p, d in sorted(hijos.items())]

    ultimo_manifest = landing.Volume.ultimo_manifest

    def lotes(self) -> list[list[dict]]:
        return [[json.loads(l) for l in v.decode().splitlines()]
                for r, v in sorted(self.archivos.items()) if r.endswith(".jsonl")]

    def manifests(self) -> list[dict]:
        return [json.loads(v) for r, v in sorted(self.archivos.items()) if "/_manifest_" in r]


@pytest.fixture
def entorno(monkeypatch):
    bq, vol = FakeBigQuery(), FakeVolume()
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proyecto-de-prueba")
    monkeypatch.setattr(extractor.bigquery, "Client", lambda **_: bq)
    monkeypatch.setattr(extractor, "datetime", Reloj)
    monkeypatch.setattr(landing, "datetime", Reloj)
    monkeypatch.setattr(landing, "Volume", lambda: vol)

    def correr(h: int, ventana: int = 3) -> int:
        Reloj.actual = hora(h)
        monkeypatch.setattr("sys.argv", ["extractor.py", "--ventana-horas", str(ventana)])
        return extractor.main()

    return SimpleNamespace(bq=bq, vol=vol, correr=correr)


TABLA = "proyecto-de-prueba.entity360_gdelt.menciones"


def test_filtro_del_respaldo_solo_si_existe_la_tabla():
    bq = FakeBigQuery()
    desde = hora(9)
    extractor.extraer(bq, TABLA, desde, hay_respaldo=False)
    assert "NOT IN" not in bq.consultas[-1]
    extractor.extraer(bq, TABLA, desde, hay_respaldo=True)
    assert extractor.FILTRO_RESPALDO.format(tabla=TABLA) in bq.consultas[-1]
    # dry run antes de cada consulta real, las dos con la misma SQL
    assert bq.consultas[0] == bq.consultas[1] and bq.consultas[2] == bq.consultas[3]


def test_dry_run_sobre_el_tope_no_ejecuta():
    bq = FakeBigQuery()
    bq.dry_run_bytes = extractor.TOPE_DRY_RUN + 1
    with pytest.raises(RuntimeError, match="dry run"):
        extractor.extraer(bq, TABLA, hora(9), hay_respaldo=True)
    assert len(bq.consultas) == 1


def test_misma_ventana_dos_veces_no_duplica(entorno):
    entorno.bq.gkg = [mencion("20260926100000-1", "BANCO_GALICIA", 10),
                      mencion("20260926100000-1", "GGAL", 10),   # mismo documento, dos entidades
                      mencion("20260926110000-7", "MELI", 11)]
    entorno.correr(12)
    assert len(entorno.bq.respaldo) == 3
    assert [len(l) for l in entorno.vol.lotes()] == [3]

    entorno.correr(13)          # la ventana de 3 h vuelve a ver las mismas menciones
    assert len(entorno.bq.respaldo) == 3
    assert [len(l) for l in entorno.vol.lotes()] == [3]
    # Segunda corrida: latido (manifest sin datos) que conserva el estado del lote anterior.
    lote, latido = entorno.vol.manifests()
    assert latido["sin_cambios"] and latido["archivo"] is None and latido["registros"] == 0
    assert latido["ultimo_archivo"] == lote["archivo"]
    assert (latido["sha256"], latido["lote_hasta"]) == (lote["sha256"], lote["lote_hasta"])


def test_latido_no_cambia_desde_donde_retoma(entorno):
    entorno.bq.gkg = [mencion("20260926100000-1", "MELI", 10)]
    entorno.correr(12)
    entorno.correr(13)                                   # latido
    entorno.bq.gkg.append(mencion("20260926130000-2", "GGAL", 13))
    entorno.correr(14)                                   # retoma desde el lote_hasta que conservó el latido
    assert [len(l) for l in entorno.vol.lotes()] == [1, 1]


def test_ventanas_superpuestas_solo_suman_lo_nuevo(entorno):
    viejo = mencion("20260926100000-1", "BANCO_GALICIA", 10)
    nuevo = mencion("20260926123000-4", "BMA", 12)
    entorno.bq.gkg = [viejo]
    entorno.correr(12)
    entorno.bq.gkg = [viejo, nuevo]
    entorno.correr(13)

    assert [r["gkg_record_id"] for r in entorno.bq.respaldo] == [viejo["gkg_record_id"], nuevo["gkg_record_id"]]
    lotes = entorno.vol.lotes()
    assert [[f["gkg_record_id"] for f in l] for l in lotes] == [[viejo["gkg_record_id"]], [nuevo["gkg_record_id"]]]
    ultimo = entorno.vol.manifests()[-1]
    assert ultimo["lote_desde"] == ultimo["lote_hasta"] == hora(13).isoformat()


def test_push_fallido_se_reintenta_en_la_corrida_siguiente(entorno):
    entorno.bq.gkg = [mencion("20260926100000-1", "BANCO_GALICIA", 10)]
    entorno.vol.falla_put = True
    with pytest.raises(RuntimeError):
        entorno.correr(12)
    assert len(entorno.bq.respaldo) == 1          # quedó respaldado del lado de GCP
    assert entorno.vol.archivos == {}

    entorno.vol.falla_put = False
    entorno.correr(13)                            # la consulta ya no la trae; el push la retoma
    assert len(entorno.bq.respaldo) == 1
    assert [[f["gkg_record_id"] for f in l] for l in entorno.vol.lotes()] == [["20260926100000-1"]]
    assert entorno.vol.manifests()[-1]["lote_hasta"] == hora(12).isoformat()
