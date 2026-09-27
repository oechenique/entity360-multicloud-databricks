"""Tarea `bronze` del job entity360-medallion (regla 08, ADR 0004).

Una tabla Iceberg gestionada por fuente (bronze.<fuente>): una fila por línea del .jsonl, con el
payload crudo y los metadatos del lote. Auto Loader con binaryFile y Trigger.AvailableNow: procesa
lo pendiente y termina. Checkpoint por fuente en ops.checkpoints/<fuente>.

Capa 2 de idempotencia (D6, capa2.py): el sha256 se calcula sobre el contenido en Spark (== el del
manifest, paso 0), los lotes repetidos quedan como `duplicado` en ops.ingestion_log y la escritura
es un MERGE insert-only por (_sha256, _linea): reprocesar no suma filas. Iceberg gestionado no admite
append en streaming (paso 0): solo MERGE, desde foreachBatch.

Un lote que el contrato de llegada (Soda, regla 09) puso en cuarentena no se ingiere: queda como
`cuarentena_contrato` en ops.ingestion_log y las demás fuentes siguen.

Un lote con `error` (hash o cantidad de registros distintos del manifest) no se ingiere y la tarea
termina fallida al final, después de procesar las demás fuentes, hasta que alguien lo revise
(estado -> `revisado` en ops.ingestion_log).
"""

import json
from pathlib import Path

import comun

spark = comun.spark_y_modulos()

import capa2  # noqa: E402  (después de spark_y_modulos, que arma sys.path)
from pyspark.sql import functions as F  # noqa: E402

COLUMNAS_CDC = """, _tabla STRING COMMENT 'Tabla del ERP legacy.'
  , _op STRING COMMENT 'insert | update | update_antes | delete (CDC de SQL Server).'
  , _lsn STRING COMMENT 'LSN del commit, hexadecimal de ancho fijo (ordena como texto).'
  , _seqval STRING COMMENT 'Orden dentro del commit.'
  , _commit_time TIMESTAMP COMMENT 'Momento del commit en el legacy.'"""


def crear_tabla(fuente: str) -> str:
    tabla = f"{comun.CATALOGO}.bronze.{fuente}"
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {tabla} (
            payload STRING COMMENT 'Registro crudo: una línea del .jsonl del productor.',
            _linea INT COMMENT 'Número de línea dentro del archivo (desde 0).',
            _sha256 STRING COMMENT 'sha256 del archivo; clave de la capa 2 de idempotencia.',
            _archivo STRING COMMENT 'Ruta del archivo de datos en landing.raw.',
            _manifest STRING COMMENT 'Manifest del lote (JSON completo).',
            _ingest_date DATE COMMENT 'Partición ingest_date del landing.',
            _ingerido_utc TIMESTAMP COMMENT 'Momento de la escritura en Bronze.'
            {COLUMNAS_CDC if fuente == "sqlserver_cdc" else ""}
        ) USING ICEBERG""")
    comun.comentar(spark, tabla, f"Bronze de {fuente}: payload crudo por línea + metadatos del lote (Auto Loader).", "bronze")
    return tabla


def procesar(fuente: str, tabla: str):
    def lote(df, batch_id):
        s = df.sparkSession
        df = df.select("path", "modificationTime", "content", F.sha2("content", 256).alias("sha256"))
        lineas = (df.select("path", "sha256", F.posexplode(F.split(F.decode("content", "utf-8"), "\n")).alias("_linea", "payload"))
                  .where(F.length("payload") > 0))
        info = {r.path: r for r in df.select("path", "modificationTime", "sha256").collect()}
        conteo = {r.path: r["count"] for r in lineas.groupBy("path").count().collect()}
        archivos = [{"ruta": p.replace("dbfs:", ""), "path": p, "sha256": r.sha256, "lineas": conteo.get(p, 0),
                     "aterrizado": r.modificationTime} for p, r in info.items()]
        manifests, contratos = {}, {}
        for a in archivos:
            m, c = Path(capa2.manifest_de(a["ruta"])), Path(capa2.contrato_de(a["ruta"]))
            manifests[a["ruta"]] = json.loads(m.read_text(encoding="utf-8")) if m.exists() else None
            contratos[a["ruta"]] = json.loads(c.read_text(encoding="utf-8")) if c.exists() else None
        ingeridos = {r.sha256: r.archivo for r in s.table(comun.INGESTION_LOG)
                     .where("estado = 'ingerido_bronze'").select("sha256", "archivo").collect()}
        decision = capa2.clasificar(archivos, manifests, ingeridos, contratos)

        ok = [(d["path"], json.dumps(d["manifest"], ensure_ascii=False, sort_keys=True))
              for d in decision if d["estado"] == "ingerido_bronze"]
        if ok:
            meta = s.createDataFrame(ok, "path string, _manifest string")
            nuevas = (lineas.join(meta, "path")
                      .select("payload", "_linea", F.col("sha256").alias("_sha256"),
                              F.regexp_replace("path", "^dbfs:", "").alias("_archivo"), "_manifest",
                              F.to_date(F.regexp_extract("path", r"ingest_date=(\d{4}-\d{2}-\d{2})", 1)).alias("_ingest_date"),
                              F.current_timestamp().alias("_ingerido_utc")))
            if fuente == "sqlserver_cdc":
                nuevas = nuevas.select("*", *[F.get_json_object("payload", f"$.{c}").alias(f"_{c}")
                                              for c in ("tabla", "op", "lsn", "seqval")],
                                       F.to_timestamp(F.get_json_object("payload", "$.commit_time")).alias("_commit_time"))
            nuevas.createOrReplaceTempView("bronze_lote")
            s.sql(f"""MERGE INTO {tabla} b USING bronze_lote l
                      ON b._sha256 = l._sha256 AND b._linea = l._linea
                      WHEN NOT MATCHED THEN INSERT *""")

        log = s.createDataFrame(
            [(fuente, d["ruta"], capa2.manifest_de(d["ruta"]), d["sha256"], d["manifest"].get("registros"),
              d["manifest"].get("extraido_utc"), d["aterrizado"], d["manifest"].get("producer_version"), d["estado"])
             for d in decision],
            "fuente string, archivo string, manifest string, sha256 string, registros bigint, extraido string, "
            "aterrizado_utc timestamp, producer_version string, estado string")
        log.select("*", F.to_timestamp("extraido").alias("extraido_utc")).drop("extraido").createOrReplaceTempView("log_lote")
        # El estado de un archivo ya registrado no se pisa con `duplicado` ni vuelve atrás desde `revisado`.
        s.sql(f"""MERGE INTO {comun.INGESTION_LOG} t USING log_lote l
                  ON t.sha256 = l.sha256 AND t.archivo = l.archivo
                  WHEN MATCHED AND t.estado NOT IN ('ingerido_bronze', 'revisado') THEN UPDATE SET estado = l.estado
                  WHEN NOT MATCHED THEN INSERT (fuente, archivo, manifest, sha256, registros, extraido_utc,
                                                aterrizado_utc, producer_version, estado)
                                        VALUES (l.fuente, l.archivo, l.manifest, l.sha256, l.registros, l.extraido_utc,
                                                l.aterrizado_utc, l.producer_version, l.estado)""")
    return lote


def main():
    for fuente in comun.FUENTES:
        tabla = crear_tabla(fuente)
        antes = spark.table(tabla).count()
        (spark.readStream.format("cloudFiles").option("cloudFiles.format", "binaryFile")
         .option("pathGlobFilter", "*.jsonl").load(f"{comun.RAW}/{fuente}")
         .writeStream.foreachBatch(procesar(fuente, tabla))
         .option("checkpointLocation", f"{comun.CHECKPOINTS}/{fuente}")
         .trigger(availableNow=True).start().awaitTermination())
        print(f"bronze.{fuente}: {spark.table(tabla).count() - antes} filas nuevas")

    resumen = spark.sql(f"SELECT fuente, estado, count(*) AS lotes FROM {comun.INGESTION_LOG} "
                        "GROUP BY fuente, estado ORDER BY fuente, estado").collect()
    print("ops.ingestion_log: " + "; ".join(f"{r.fuente}/{r.estado}={r.lotes}" for r in resumen))
    errores = [r for r in resumen if r.estado == "error"]
    if errores:
        raise RuntimeError(f"lotes con error en ops.ingestion_log (revisar y marcar `revisado`): {errores}")


main()
