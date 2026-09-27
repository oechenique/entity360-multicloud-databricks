"""Paso 0 de la fase 6 (regla 08): verificaciones en serverless antes de construir el medallion.

1. Auto Loader con binaryFile sobre el volume, Trigger.AvailableNow: ¿qué archivos ve con y sin
   pathGlobFilter? (los _manifest_*.json no tienen que entrar como datos)
2. sha2(content, 256) en Spark == sha256 del manifest de cada lote (base de la capa 2).
3. foreachBatch: leer el manifest desde /Volumes, MERGE insert-only por (sha256, linea); un
   segundo stream sobre los mismos archivos no suma filas; una excepción deja el checkpoint sin avanzar.
4. Iceberg gestionado: CREATE, MERGE, append en streaming y MERGE desde foreachBatch.
5. rapidfuzz (dependencia del environment serverless), en el driver y en una pandas UDF.
6. system.billing.usage: ¿está visible en Free Edition?

Todo lo que crea usa el prefijo _paso0 y se borra al final. Resultado: JSON por stdout y en
/Volumes/entity360/ops/checkpoints/_paso0/resultado.json.
"""

import hashlib
import json
import traceback
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = SparkSession.builder.getOrCreate()

RAW = "/Volumes/entity360/landing/raw"
FUENTE = "wikidata"                      # un lote chico (20 registros)
BASE = "/Volumes/entity360/ops/checkpoints/_paso0"
T = "entity360.ops._paso0"
res: dict = {}


def paso(nombre):
    def deco(fn):
        try:
            res[nombre] = {"ok": True, **(fn() or {})}
        except Exception as e:  # se registra y se sigue con las demás verificaciones
            res[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:600]}",
                           "traza": traceback.format_exc()[-1500:]}
        return fn
    return deco


def autoloader(glob: str | None):
    r = (spark.readStream.format("cloudFiles").option("cloudFiles.format", "binaryFile"))
    if glob:
        r = r.option("pathGlobFilter", glob)
    return r.load(f"{RAW}/{FUENTE}")


def limpiar():
    for t in ("archivos_todos", "archivos_jsonl", "bronze", "ice", "ice_stream", "ice_merge"):
        spark.sql(f"DROP TABLE IF EXISTS {T}_{t}")


limpiar()
import shutil
shutil.rmtree(BASE, ignore_errors=True)


@paso("1_autoloader_binaryfile")
def _():
    out = {}
    for nombre, glob in (("todos", None), ("jsonl", "*.jsonl")):
        (autoloader(glob).select("path", "length", F.sha2("content", 256).alias("sha256"))
         .writeStream.option("checkpointLocation", f"{BASE}/ck_{nombre}")
         .trigger(availableNow=True).toTable(f"{T}_archivos_{nombre}").awaitTermination())
        out[f"archivos_{nombre}"] = sorted(r.path.rsplit("/", 1)[1] for r in spark.table(f"{T}_archivos_{nombre}").collect())
    return out


@paso("2_sha256_igual_al_manifest")
def _():
    comparaciones = []
    for r in spark.table(f"{T}_archivos_jsonl").collect():
        ruta = Path(r.path.replace("dbfs:", ""))
        ts = ruta.stem.rsplit("_", 1)[1]
        manifest = json.loads((ruta.parent / f"_manifest_{ts}.json").read_text(encoding="utf-8"))
        local = hashlib.sha256(ruta.read_bytes()).hexdigest()
        comparaciones.append({"archivo": ruta.name, "spark_igual_manifest": r.sha256 == manifest["sha256"],
                              "python_igual_manifest": local == manifest["sha256"]})
    assert comparaciones and all(c["spark_igual_manifest"] for c in comparaciones), comparaciones
    return {"lotes": comparaciones}


def merge_bronze(df, batch_id):
    """Como el Bronze real: manifest leído desde /Volumes dentro del foreachBatch + MERGE insert-only."""
    s = df.sparkSession
    manifests = {}
    for r in df.select("path").collect():
        ruta = Path(r.path.replace("dbfs:", ""))
        ts = ruta.stem.rsplit("_", 1)[1]
        m = ruta.parent / f"_manifest_{ts}.json"
        if not m.exists():
            raise RuntimeError(f"sin manifest todavía: {m.name}")
        manifests[r.path] = json.loads(m.read_text(encoding="utf-8"))["registros"]
    lineas = (df.select("path", F.sha2("content", 256).alias("_sha256"),
                        F.posexplode(F.split(F.decode("content", "utf-8"), "\n")).alias("_linea", "payload"))
              .where(F.length("payload") > 0))
    lineas.createOrReplaceTempView("lote")
    s.sql(f"""MERGE INTO {T}_bronze b USING lote l
              ON b._sha256 = l._sha256 AND b._linea = l._linea
              WHEN NOT MATCHED THEN INSERT (_sha256, _linea, payload, _archivo)
                                    VALUES (l._sha256, l._linea, l.payload, l.path)""")


@paso("3_foreachbatch_merge_idempotente")
def _():
    spark.sql(f"CREATE TABLE {T}_bronze (_sha256 STRING, _linea INT, payload STRING, _archivo STRING)")
    conteos = []
    for corrida in ("a", "b"):   # dos checkpoints distintos: el segundo relee los mismos archivos
        (autoloader("*.jsonl").writeStream.foreachBatch(merge_bronze)
         .option("checkpointLocation", f"{BASE}/ck_bronze_{corrida}")
         .trigger(availableNow=True).start().awaitTermination())
        conteos.append(spark.table(f"{T}_bronze").count())
    assert conteos[0] > 0 and conteos[0] == conteos[1], conteos

    def falla(df, batch_id):
        raise RuntimeError("falla a propósito")
    ck = f"{BASE}/ck_falla"
    error = None
    try:
        (autoloader("*.jsonl").writeStream.foreachBatch(falla).option("checkpointLocation", ck)
         .trigger(availableNow=True).start().awaitTermination())
    except Exception as e:
        error = type(e).__name__
    # Después de la falla, el mismo checkpoint vuelve a entregar los archivos.
    (autoloader("*.jsonl").select("path").writeStream.option("checkpointLocation", ck)
     .trigger(availableNow=True).toTable(f"{T}_archivos_reintento").awaitTermination())
    reintento = spark.table(f"{T}_archivos_reintento").count()
    spark.sql(f"DROP TABLE IF EXISTS {T}_archivos_reintento")
    assert error and reintento > 0, (error, reintento)
    return {"filas_tras_corrida": conteos, "excepcion_propagada": error, "archivos_reentregados_tras_falla": reintento}


@paso("4_iceberg_gestionado")
def _():
    out = {}
    spark.sql(f"CREATE TABLE {T}_ice (id INT, v STRING) USING ICEBERG")
    spark.sql(f"INSERT INTO {T}_ice VALUES (1, 'a'), (2, 'b')")
    try:
        spark.sql(f"""MERGE INTO {T}_ice t USING (SELECT 2 AS id, 'B' AS v UNION ALL SELECT 3, 'c') s
                      ON t.id = s.id WHEN MATCHED THEN UPDATE SET v = s.v WHEN NOT MATCHED THEN INSERT *""")
        out["merge"] = sorted((r.id, r.v) for r in spark.table(f"{T}_ice").collect())
    except Exception as e:
        out["merge"] = f"ERROR {type(e).__name__}: {str(e)[:300]}"
    try:
        spark.sql(f"CREATE TABLE {T}_ice_stream (path STRING) USING ICEBERG")
        (autoloader("*.jsonl").select("path").writeStream.option("checkpointLocation", f"{BASE}/ck_ice")
         .trigger(availableNow=True).toTable(f"{T}_ice_stream").awaitTermination())
        out["append_streaming"] = spark.table(f"{T}_ice_stream").count()
    except Exception as e:
        out["append_streaming"] = f"ERROR {type(e).__name__}: {str(e)[:300]}"
    try:
        spark.sql(f"CREATE TABLE {T}_ice_merge (_sha256 STRING, _linea INT, payload STRING, _archivo STRING) USING ICEBERG")

        def merge_ice(df, batch_id):
            df.select("path", F.sha2("content", 256).alias("_sha256"),
                      F.posexplode(F.split(F.decode("content", "utf-8"), "\n")).alias("_linea", "payload")
                      ).createOrReplaceTempView("lote_ice")
            df.sparkSession.sql(f"""MERGE INTO {T}_ice_merge b USING lote_ice l
                ON b._sha256 = l._sha256 AND b._linea = l._linea
                WHEN NOT MATCHED THEN INSERT (_sha256, _linea, payload, _archivo) VALUES (l._sha256, l._linea, l.payload, l.path)""")
        (autoloader("*.jsonl").writeStream.foreachBatch(merge_ice).option("checkpointLocation", f"{BASE}/ck_ice_merge")
         .trigger(availableNow=True).start().awaitTermination())
        out["merge_foreachbatch"] = spark.table(f"{T}_ice_merge").count()
    except Exception as e:
        out["merge_foreachbatch"] = f"ERROR {type(e).__name__}: {str(e)[:300]}"
    out["formato"] = spark.sql(f"DESCRIBE DETAIL {T}_ice").select("format").first()[0]
    return out


@paso("5_rapidfuzz")
def _():
    import pandas as pd
    import rapidfuzz
    from rapidfuzz import fuzz

    @F.pandas_udf("double")
    def similitud(a: pd.Series, b: pd.Series) -> pd.Series:
        from rapidfuzz import fuzz as f
        return pd.Series([f.token_set_ratio(x, y) / 100 for x, y in zip(a, b)])

    df = spark.createDataFrame([("PAMPA ENERGIA", "PAMPA ENERGY"), ("BANCO MACRO", "MACRO BANK")], "a string, b string")
    return {"version": rapidfuzz.__version__,
            "driver": fuzz.token_set_ratio("BANCO MACRO", "MACRO BANK"),
            "udf": [round(r.s, 3) for r in df.select(similitud("a", "b").alias("s")).collect()]}


@paso("6_system_billing_usage")
def _():
    r = spark.sql("""SELECT count(*) AS filas, max(usage_date) AS ultima,
                            round(sum(CASE WHEN usage_date >= current_date() - 7 THEN usage_quantity END), 3) AS dbu_7d
                     FROM system.billing.usage""").first()
    return {"filas": r.filas, "ultima_fecha": str(r.ultima), "dbu_ultimos_7_dias": r.dbu_7d}


limpiar()
salida = json.dumps(res, indent=2, ensure_ascii=False, default=str)
Path(BASE).mkdir(parents=True, exist_ok=True)
for p in Path(BASE).iterdir():
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
(Path(BASE) / "resultado.json").write_text(salida, encoding="utf-8")
print(salida)
