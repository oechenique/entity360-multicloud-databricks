"""Constantes y utilidades compartidas por las tareas del job entity360-medallion (ADR 0004)."""

import sys
from pathlib import Path

CATALOGO = "entity360"
RAW = f"/Volumes/{CATALOGO}/landing/raw"
CHECKPOINTS = f"/Volumes/{CATALOGO}/ops/checkpoints"
INGESTION_LOG = f"{CATALOGO}.ops.ingestion_log"

# Fuentes con productor propio (regla 01). GLEIF llega por el CDC del legacy (sqlserver_cdc).
FUENTES = ("sqlserver_cdc", "sec_edgar", "gdelt", "opensanctions", "wikidata")

# Claves naturales del ERP legacy (legacy/sql): una tabla _hist por tabla en Silver.
CLAVES_CDC = {
    "entidad": ("lei",),
    "direccion": ("lei", "tipo"),
    "nombre_alternativo": ("lei", "orden"),
    "relacion": ("lei_hijo", "lei_padre", "tipo"),
}


def spark_y_modulos():
    """SparkSession y el directorio del código en sys.path. Los módulos puros se serializan por
    valor en las UDFs y en foreachBatch: en serverless corren en procesos que no ven los workspace files."""
    aqui = Path(__file__).resolve().parent
    if str(aqui) not in sys.path:
        sys.path.insert(0, str(aqui))
    from pyspark import cloudpickle
    from pyspark.sql import SparkSession

    import capa2
    import identidades
    import normalizacion
    import scd2
    for m in (capa2, identidades, normalizacion, scd2, sys.modules[__name__]):
        cloudpickle.register_pickle_by_value(m)
    return SparkSession.builder.getOrCreate()


def comentar(spark, tabla: str, comentario: str, capa: str, columnas: dict[str, str] | None = None):
    """Comentarios y tags desde el inicio (regla 03): los usa Genie."""
    def q(s):
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
    spark.sql(f"COMMENT ON TABLE {tabla} IS {q(comentario)}")
    spark.sql(f"ALTER TABLE {tabla} SET TAGS ('capa' = '{capa}')")
    for col, texto in (columnas or {}).items():
        spark.sql(f"ALTER TABLE {tabla} ALTER COLUMN {col} COMMENT {q(texto)}")


def ddl(df) -> str:
    return ", ".join(f"`{f.name}` {f.dataType.simpleString()}" for f in df.schema.fields)


def publicar(spark, df, tabla: str, claves: list[str], comentario: str, capa: str,
             columnas: dict[str, str] | None = None, borrar_faltantes: bool = True) -> int:
    """MERGE por clave natural: actualiza, inserta y (si se pide) borra lo que ya no está en la fuente.
    Iceberg gestionado se escribe solo con MERGE (paso 0)."""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {tabla} ({ddl(df)}) USING ICEBERG")
    comentar(spark, tabla, comentario, capa, columnas)
    df.createOrReplaceTempView("fuente_publicar")
    on = " AND ".join(f"t.`{c}` <=> s.`{c}`" for c in claves)
    spark.sql(f"""MERGE INTO {tabla} t USING fuente_publicar s ON {on}
                  WHEN MATCHED THEN UPDATE SET *
                  WHEN NOT MATCHED THEN INSERT *
                  {"WHEN NOT MATCHED BY SOURCE THEN DELETE" if borrar_faltantes else ""}""")
    return spark.table(tabla).count()
