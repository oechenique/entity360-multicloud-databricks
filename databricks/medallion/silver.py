"""Tarea `silver` del job entity360-medallion (regla 08, ADR 0004).

- GLEIF (CDC del legacy): SCD tipo 2 por tabla del ERP (silver.gleif_<tabla>_hist) con scd2.aplicar
  por clave (applyInPandas), más una vista con lo vigente (silver.gleif_<tabla>).
- SEC EDGAR, OpenSanctions, Wikidata y GDELT: se recalculan enteras desde Bronze (son chicas) y se
  deduplican por clave natural, quedándose con la última extracción (capa 3 de idempotencia, D6).
- Nombres, países y ciudades normalizados con normalizacion.py (pandas UDFs).
- Registros que no cumplen: silver._quarantine con el motivo. `bloqueante` = el registro no pasa;
  si no, el registro pasa y se descarta solo el dato inválido (p. ej. un LEI con dígito de control
  inválido en OpenSanctions).

Todas las tablas son Iceberg gestionadas y se escriben solo con MERGE (paso 0).
"""

import json

import comun

spark = comun.spark_y_modulos()

import pandas as pd  # noqa: E402
from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

import normalizacion as N  # noqa: E402
import scd2  # noqa: E402

S = f"{comun.CATALOGO}.silver"
B = f"{comun.CATALOGO}.bronze"
NOMBRE = "struct<norm:string, sin_forma:string, forma:string, tokens:array<string>>"


# ------------------------------------------------------------------ UDFs de normalización

@F.pandas_udf(NOMBRE)
def nombre_udf(s: pd.Series) -> pd.DataFrame:
    return pd.DataFrame([N.nombre(x) for x in s], columns=["norm", "sin_forma", "forma", "tokens"])


def pais_udf(fuente: str):
    @F.pandas_udf("string")
    def f(s: pd.Series) -> pd.Series:
        return pd.Series([N.pais(x, fuente) for x in s], dtype="object")
    return f


@F.pandas_udf("string")
def ciudad_udf(s: pd.Series) -> pd.Series:
    return pd.Series([N.ciudad(x) for x in s], dtype="object")


@F.pandas_udf("boolean")
def lei_valido_udf(s: pd.Series) -> pd.Series:
    return pd.Series([N.lei_valido(x) for x in s], dtype="bool")


@F.pandas_udf("array<string>")
def leis_validos_udf(s: pd.Series) -> pd.Series:
    return pd.Series([[x for x in (v if v is not None else []) if N.lei_valido(x)] for v in s], dtype="object")


def con_nombre(df, col: str, prefijo: str = "nombre"):
    n = nombre_udf(F.col(col))
    return df.select("*", n["norm"].alias(f"{prefijo}_norm"), n["sin_forma"].alias(f"{prefijo}_sin_forma"),
                     n["forma"].alias("forma_juridica") if prefijo == "nombre" else n["forma"].alias(f"{prefijo}_forma"),
                     n["tokens"].alias(f"{prefijo}_tokens"))


# ------------------------------------------------------------------ escritura

def ddl(df) -> str:
    return ", ".join(f"`{f.name}` {f.dataType.simpleString()}" for f in df.schema.fields)


def publicar(df, tabla: str, claves: list[str], comentario: str, columnas: dict[str, str] | None = None,
             borrar_faltantes: bool = True) -> int:
    """MERGE por clave natural: actualiza, inserta y (si se pide) borra lo que ya no está en la fuente."""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {tabla} ({ddl(df)}) USING ICEBERG")
    comun.comentar(spark, tabla, comentario, "silver", columnas)
    df.createOrReplaceTempView("fuente_silver")
    on = " AND ".join(f"t.`{c}` <=> s.`{c}`" for c in claves)
    spark.sql(f"""MERGE INTO {tabla} t USING fuente_silver s ON {on}
                  WHEN MATCHED THEN UPDATE SET *
                  WHEN NOT MATCHED THEN INSERT *
                  {"WHEN NOT MATCHED BY SOURCE THEN DELETE" if borrar_faltantes else ""}""")
    return spark.table(tabla).count()


def cuarentena(df, fuente: str, motivo_col: str, bloqueante: bool):
    """df con _archivo, _linea, payload y una columna con el motivo (null = sin problema)."""
    q = (df.where(F.col(motivo_col).isNotNull())
         .select(F.lit(fuente).alias("fuente"), "_archivo", "_linea", "payload",
                 F.col(motivo_col).alias("motivo"), F.lit(bloqueante).alias("bloqueante"),
                 F.current_timestamp().alias("detectado_utc")))
    tabla = f"{S}._quarantine"
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {tabla} (fuente STRING, _archivo STRING, _linea INT, payload STRING,
                  motivo STRING, bloqueante BOOLEAN, detectado_utc TIMESTAMP) USING ICEBERG""")
    comun.comentar(spark, tabla, "Registros que no cumplen el esquema de su fuente, con el motivo. "
                   "bloqueante = el registro no pasa a Silver; si no, se descarta solo el dato inválido.", "silver")
    q.createOrReplaceTempView("q_lote")
    spark.sql(f"""MERGE INTO {tabla} t USING q_lote s
                  ON t.fuente = s.fuente AND t._archivo = s._archivo AND t._linea = s._linea AND t.motivo = s.motivo
                  WHEN NOT MATCHED THEN INSERT *""")
    return q.count()


def ultima(df, claves: list[str], orden: list):
    w = Window.partitionBy(*claves).orderBy(*orden)
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


# ------------------------------------------------------------------ GLEIF: SCD2 sobre el CDC

ESQUEMAS_CDC = {
    "entidad": "lei string, nombre_legal string, idioma_nombre string, jurisdiccion string, categoria string, "
               "forma_juridica_codigo string, forma_juridica_otra string, estado_entidad string, "
               "fecha_creacion_entidad date, estado_registro string, fecha_registro_inicial timestamp, "
               "fecha_ultima_actualizacion timestamp, fecha_proxima_renovacion timestamp, lou_gestor string, "
               "alcance string, modificado_en timestamp",
    "direccion": "lei string, tipo string, linea1 string, numero string, linea_adicional string, ciudad string, "
                 "region string, pais string, codigo_postal string, modificado_en timestamp",
    "nombre_alternativo": "lei string, orden int, nombre string, tipo string, idioma string, modificado_en timestamp",
    "relacion": "lei_hijo string, lei_padre string, tipo string, estado_relacion string, estado_registro string, "
                "fecha_inicio timestamp, fecha_ultima_actualizacion timestamp, modificado_en timestamp",
}
SALIDA_SCD2 = ("_clave string, accion string, datos string, _hash string, _op string, _lsn string, _seqval string, "
               "valido_desde string, valido_hasta string")


def scd2_grupo(pdf: pd.DataFrame) -> pd.DataFrame:
    cambios = [{"op": r.op, "lsn": r.lsn, "seqval": r.seqval, "commit_time": r.commit_time, "datos": json.loads(r.datos)}
               for r in pdf.itertuples() if r.tipo == "cambio"]
    previa = [r for r in pdf.itertuples() if r.tipo == "ultima"]
    ult = None
    if previa:
        p = previa[0]
        ult = {"_hash": p.hash, "_lsn": p.lsn, "_seqval": p.seqval, "valido_hasta": p.valido_hasta}
    cierre, nuevas = scd2.aplicar(cambios, ult)
    clave = pdf["_clave"].iloc[0]
    filas = []
    if cierre:
        filas.append((clave, "cerrar", None, None, None, previa[0].lsn, previa[0].seqval, None, cierre))
    for n in nuevas:
        meta = {k: n.pop(k) for k in ("_hash", "_op", "_lsn", "_seqval", "valido_desde", "valido_hasta")}
        filas.append((clave, "nueva", json.dumps(n, ensure_ascii=False), meta["_hash"], meta["_op"], meta["_lsn"],
                      meta["_seqval"], meta["valido_desde"], meta["valido_hasta"]))
    return pd.DataFrame(filas, columns=[c.split()[0] for c in SALIDA_SCD2.split(", ")])


def gleif():
    bronze = spark.table(f"{B}.sqlserver_cdc")
    datos = F.get_json_object("payload", "$.datos")
    malos = bronze.select("*", F.when(datos.isNull(), "payload sin datos")
                          .when(~F.col("_op").isin("insert", "update", "update_antes", "delete"), "operación desconocida")
                          .when(~F.col("_tabla").isin(*comun.CLAVES_CDC), "tabla desconocida")
                          .alias("motivo"))
    en_cuarentena = cuarentena(malos, "sqlserver_cdc", "motivo", True)
    validos = malos.where("motivo IS NULL")
    for t, claves in comun.CLAVES_CDC.items():
        hist = f"{S}.gleif_{t}_hist"
        esquema = ESQUEMAS_CDC[t]
        clave = F.to_json(F.struct(*[F.get_json_object(datos, f"$.{c}").alias(c) for c in claves]))
        cambios = (validos.where(F.col("_tabla") == t)
                   .select(clave.alias("_clave"), F.lit("cambio").alias("tipo"), F.col("_op").alias("op"),
                           F.col("_lsn").alias("lsn"), F.col("_seqval").alias("seqval"),
                           F.get_json_object("payload", "$.commit_time").alias("commit_time"), datos.alias("datos"),
                           F.lit(None).cast("string").alias("hash"), F.lit(None).cast("string").alias("valido_hasta")))
        vacia = spark.createDataFrame([], esquema)
        muestra = con_nombre(vacia, "nombre_legal") if t == "entidad" else (
            con_nombre(vacia, "nombre") if t == "nombre_alternativo" else vacia)
        spark.sql(f"""CREATE TABLE IF NOT EXISTS {hist} (_clave string, {ddl(muestra)}, _hash string, _op string,
                      _lsn string, _seqval string, valido_desde timestamp, valido_hasta timestamp) USING ICEBERG""")
        comun.comentar(spark, hist, f"GLEIF ({t}) desde el CDC del legacy, con historia (SCD tipo 2). "
                       "Vigente = valido_hasta IS NULL.", "silver",
                       {"_clave": "Clave natural de la fila del ERP, como JSON.",
                        "valido_desde": "Commit que abrió esta versión.",
                        "valido_hasta": "Commit que la cerró (update o delete); null = vigente."})
        previas = ultima(spark.table(hist), ["_clave"], [F.col("_lsn").desc(), F.col("_seqval").desc()])
        previas = previas.select("_clave", F.lit("ultima").alias("tipo"), F.lit(None).cast("string").alias("op"),
                                 F.col("_lsn").alias("lsn"), F.col("_seqval").alias("seqval"),
                                 F.lit(None).cast("string").alias("commit_time"), F.lit(None).cast("string").alias("datos"),
                                 F.col("_hash").alias("hash"), F.col("valido_hasta").cast("string").alias("valido_hasta"))
        previas = previas.join(cambios.select("_clave").distinct(), "_clave")   # solo claves con cambios
        res = cambios.unionByName(previas).groupBy("_clave").applyInPandas(scd2_grupo, SALIDA_SCD2)
        tipado = res.select("*", F.from_json("datos", esquema).alias("d")).select(
            "_clave", "accion", "d.*", "_hash", "_op", "_lsn", "_seqval",
            F.to_timestamp("valido_desde").alias("valido_desde"), F.to_timestamp("valido_hasta").alias("valido_hasta"))
        if t == "entidad":
            tipado = con_nombre(tipado, "nombre_legal")
        elif t == "nombre_alternativo":
            tipado = con_nombre(tipado, "nombre")
        tipado.createOrReplaceTempView("scd2_lote")
        cols = [c for c in spark.table(hist).columns]
        spark.sql(f"""MERGE INTO {hist} t USING scd2_lote s
                      ON t._clave = s._clave AND t._lsn = s._lsn AND t._seqval = s._seqval
                      WHEN MATCHED AND s.accion = 'cerrar' THEN UPDATE SET valido_hasta = s.valido_hasta
                      WHEN NOT MATCHED AND s.accion = 'nueva' THEN INSERT ({", ".join(f"`{c}`" for c in cols)})
                                                           VALUES ({", ".join(f"s.`{c}`" for c in cols)})""")
        spark.sql(f"CREATE OR REPLACE VIEW {S}.gleif_{t} AS SELECT * EXCEPT (_clave) FROM {hist} WHERE valido_hasta IS NULL")
        vig = spark.table(f"{S}.gleif_{t}").count()
        print(f"silver.gleif_{t}_hist: {spark.table(hist).count()} versiones, {vig} vigentes")
    return en_cuarentena


def gleif_lei_valido():
    """Marca de LEI válido (ISO 17442) sobre lo vigente: 68 LEI argentinos ANNULLED fallan (normalizacion.lei_valido)."""
    df = spark.table(f"{S}.gleif_entidad").select("lei").distinct()
    df = df.select("lei", lei_valido_udf("lei").alias("lei_valido"))
    return publicar(df, f"{S}.gleif_lei", ["lei"],
                    "LEI del legacy con su validación ISO 17442. Los inválidos son del registro oficial (ANNULLED): "
                    "se marcan y no se usan como candidatos de matching.",
                    {"lei_valido": "Dígitos de control mod 97 correctos."})


# ------------------------------------------------------------------ SEC EDGAR

SEC = """cik bigint, ticker string, extraido_utc string, ultima_presentacion struct<fecha:string, form:string>,
submissions struct<name:string, tickers:array<string>, exchanges:array<string>, sic:string, sicDescription:string,
ein:string, lei:string, website:string, stateOfIncorporation:string, category:string,
formerNames:array<struct<name:string, `from`:string, `to`:string>>,
addresses:struct<business:struct<city:string, stateOrCountry:string, countryCode:string, country:string>>>"""


def sec_edgar():
    b = spark.table(f"{B}.sec_edgar").select("*", F.from_json("payload", SEC).alias("r"))
    b = b.select("*", F.when(F.col("r").isNull(), "JSON inválido").when(F.col("r.cik").isNull(), "sin CIK")
                 .when(F.col("r.submissions.name").isNull(), "sin nombre").alias("motivo"))
    q = cuarentena(b, "sec_edgar", "motivo", True)
    r = ultima(b.where("motivo IS NULL"), ["r.cik"], [F.col("r.extraido_utc").desc(), F.col("_ingerido_utc").desc()])
    sub, neg = "r.submissions", "r.submissions.addresses.business"
    emisor = r.select(
        F.col("r.cik").alias("cik"), F.col("r.ticker").alias("ticker"), F.col(f"{sub}.tickers").alias("tickers"),
        F.col(f"{sub}.exchanges").alias("bolsas"), F.col(f"{sub}.name").alias("nombre"),
        F.col(f"{sub}.sic").alias("sic"), F.col(f"{sub}.sicDescription").alias("sic_descripcion"),
        F.col(f"{sub}.ein").alias("ein"), F.nullif(F.col(f"{sub}.website"), F.lit("")).alias("sitio_web"),
        F.col(f"{sub}.category").alias("categoria"),
        pais_udf("sec_edgar")(F.col(f"{sub}.stateOfIncorporation")).alias("pais_incorporacion"),
        F.coalesce(pais_udf("sec_edgar")(F.col(f"{neg}.stateOrCountry")),
                   pais_udf("sec_edgar")(F.col(f"{neg}.countryCode")),
                   pais_udf("sec_edgar")(F.col(f"{neg}.country"))).alias("pais_sede"),
        ciudad_udf(F.col(f"{neg}.city")).alias("ciudad_sede"),
        F.to_date("r.ultima_presentacion.fecha").alias("ultima_presentacion"),
        F.col("r.ultima_presentacion.form").alias("ultima_presentacion_form"),
        F.to_timestamp("r.extraido_utc").alias("extraido_utc"), "_archivo")
    emisor = con_nombre(emisor, "nombre")
    n1 = publicar(emisor, f"{S}.sec_emisor", ["cik"], "Emisores ante la SEC (EDGAR), uno por CIK, última extracción.",
                  {"cik": "Central Index Key de la SEC.", "pais_incorporacion": "ISO 3166-1 alfa-2 (código EDGAR).",
                   "nombre_tokens": "Tokens canónicos (inglés llevado a castellano) para el matching."})
    anteriores = r.select(F.col("r.cik").alias("cik"), F.explode_outer(f"{sub}.formerNames").alias("f")).where("f IS NOT NULL")
    nombres = (r.select(F.col("r.cik").alias("cik"), F.col(f"{sub}.name").alias("nombre"), F.lit("actual").alias("tipo"),
                        F.lit(None).cast("date").alias("desde"), F.lit(None).cast("date").alias("hasta"))
               .unionByName(anteriores.select("cik", F.col("f.name").alias("nombre"), F.lit("anterior").alias("tipo"),
                                              F.to_date(F.substring("f.from", 1, 10)).alias("desde"),
                                              F.to_date(F.substring("f.to", 1, 10)).alias("hasta"))))
    n2 = publicar(con_nombre(nombres, "nombre"), f"{S}.sec_nombre", ["cik", "nombre", "tipo"],
                  "Nombres de cada emisor de la SEC: el actual y los anteriores (formerNames).")
    return q, n1, n2


# ------------------------------------------------------------------ OpenSanctions

OS = """id string, schema string, name string, aliases array<string>, countries array<string>, leis array<string>,
identifiers array<string>, dataset array<string>, sanctions string, program_ids array<string>, first_seen string,
last_change string, addresses string"""


def opensanctions():
    b = spark.table(f"{B}.opensanctions").select("*", F.from_json("payload", OS).alias("r"))
    b = b.select("*", F.when(F.col("r").isNull(), "JSON inválido").when(F.col("r.id").isNull(), "sin id")
                 .when(F.col("r.name").isNull(), "sin nombre").alias("motivo"))
    q = cuarentena(b, "opensanctions", "motivo", True)
    ok = b.where("motivo IS NULL")
    ok = ok.select("*", leis_validos_udf("r.leis").alias("leis_ok"))
    q += cuarentena(ok.select("*", F.when(F.size(F.array_except(F.coalesce("r.leis", F.array()), "leis_ok")) > 0,
                                          F.concat(F.lit("LEI inválido descartado: "),
                                                   F.array_join(F.array_except("r.leis", "leis_ok"), ","))).alias("m")),
                    "opensanctions", "m", False)
    r = ultima(ok, ["r.id"], [F.col("r.last_change").desc(), F.col("_ingerido_utc").desc()])
    leis_universo = spark.table(f"{S}.gleif_entidad").select("lei")
    ent = r.select(
        F.col("r.id").alias("id"), F.col("r.schema").alias("esquema"), F.col("r.name").alias("nombre"),
        F.coalesce("r.aliases", F.array()).alias("aliases"),
        F.transform(F.coalesce("r.countries", F.array()), lambda c: F.upper(c)).alias("paises"),
        F.col("leis_ok").alias("leis"), F.coalesce("r.identifiers", F.array()).alias("identificadores"),
        F.coalesce("r.dataset", F.array()).alias("datasets"), F.col("r.sanctions").alias("sanciones"),
        (F.col("r.sanctions").isNotNull() | (F.size(F.coalesce("r.program_ids", F.array())) > 0)).alias("sancionada"),
        F.to_timestamp("r.first_seen").alias("primera_vez"), F.to_timestamp("r.last_change").alias("ultimo_cambio"),
        F.col("r.addresses").alias("direcciones"), "_archivo")
    en_legacy = (ent.select("id", F.explode("leis").alias("lei")).join(leis_universo, "lei")
                 .select("id").distinct().withColumn("lei_en_legacy", F.lit(True)))
    ent = (ent.join(en_legacy, "id", "left")
           .withColumn("en_universo", F.array_contains("paises", "AR") | F.coalesce("lei_en_legacy", F.lit(False)))
           .drop("lei_en_legacy"))
    ent = con_nombre(ent, "nombre")
    n1 = publicar(ent, f"{S}.opensanctions_entidad", ["id"],
                  "Entidades de OpenSanctions (no personas), una por id. en_universo = país AR o un LEI del legacy: "
                  "solo esas entran a la resolución. Datos CC BY-NC 4.0 (opensanctions.org).",
                  {"sancionada": "Tiene sanción o programa asociado.",
                   "en_universo": "País AR o comparte LEI con el legacy (entra a la resolución)."})
    nombres = (ent.select("id", "nombre", F.lit("nombre").alias("tipo"))
               .unionByName(ent.select("id", F.explode("aliases").alias("nombre"), F.lit("alias").alias("tipo")))
               .dropDuplicates(["id", "nombre"]))
    n2 = publicar(con_nombre(nombres, "nombre"), f"{S}.opensanctions_nombre", ["id", "nombre"],
                  "Nombre y aliases de cada entidad de OpenSanctions.")
    return q, n1, n2


# ------------------------------------------------------------------ Wikidata

WD = """qid string, etiqueta_es string, etiqueta_en string, leis array<string>, ciks array<bigint>,
tickers array<string>, paises array<string>, sitios_web array<string>, motivos array<string>"""


def wikidata():
    b = spark.table(f"{B}.wikidata").select("*", F.from_json("payload", WD).alias("r"))
    b = b.select("*", F.when(F.col("r").isNull(), "JSON inválido").when(F.col("r.qid").isNull(), "sin QID")
                 .when(F.coalesce("r.etiqueta_es", "r.etiqueta_en").isNull(), "sin etiqueta").alias("motivo"))
    q = cuarentena(b, "wikidata", "motivo", True)
    ok = b.where("motivo IS NULL").select("*", leis_validos_udf("r.leis").alias("leis_ok"))
    r = ultima(ok, ["r.qid"], [F.col("_ingerido_utc").desc()])
    item = r.select(
        F.col("r.qid").alias("qid"), F.col("r.etiqueta_es").alias("etiqueta_es"), F.col("r.etiqueta_en").alias("etiqueta_en"),
        F.col("leis_ok").alias("leis"), F.coalesce("r.ciks", F.array()).alias("ciks"),
        F.coalesce("r.tickers", F.array()).alias("tickers"),
        F.transform(F.coalesce("r.tickers", F.array()), lambda t: F.upper(F.element_at(F.split(t, ":"), -1))).alias("simbolos"),
        F.coalesce("r.paises", F.array()).alias("paises"), F.coalesce("r.sitios_web", F.array()).alias("sitios_web"),
        F.transform(F.coalesce("r.sitios_web", F.array()),
                    lambda u: F.regexp_replace(F.lower(F.parse_url(u, F.lit("HOST"))), "^www\\.", "")).alias("dominios"),
        "_archivo")
    n1 = publicar(con_nombre(item.withColumn("nombre", F.coalesce("etiqueta_es", "etiqueta_en")), "nombre"),
                  f"{S}.wikidata_item", ["qid"],
                  "Ítems de Wikidata del universo: puente de identificadores (LEI P1278, CIK P5531, ticker). "
                  "Señal extra de matching, no verdad de referencia (D11). CC0.",
                  {"simbolos": "Ticker sin la bolsa (NYSE:YPF -> YPF).", "dominios": "Host del sitio web, sin www."})
    nombres = (item.select("qid", F.col("etiqueta_es").alias("nombre"), F.lit("es").alias("tipo"))
               .unionByName(item.select("qid", F.col("etiqueta_en").alias("nombre"), F.lit("en").alias("tipo")))
               .where("nombre IS NOT NULL").dropDuplicates(["qid", "nombre"]))
    n2 = publicar(con_nombre(nombres, "nombre"), f"{S}.wikidata_nombre", ["qid", "nombre"], "Etiquetas de cada ítem de Wikidata.")
    return q, n1, n2


# ------------------------------------------------------------------ GDELT

GD = """gkg_record_id string, entidad string, fecha_gdelt string, medio string, url string, tono double,
formas array<string>, lote_utc string"""


def gdelt():
    b = spark.table(f"{B}.gdelt").select("*", F.from_json("payload", GD).alias("r"))
    b = b.select("*", F.when(F.col("r").isNull(), "JSON inválido").when(F.col("r.gkg_record_id").isNull(), "sin GKGRECORDID")
                 .when(F.col("r.entidad").isNull(), "sin entidad").alias("motivo"))
    q = cuarentena(b, "gdelt", "motivo", True)
    r = ultima(b.where("motivo IS NULL"), ["r.gkg_record_id", "r.entidad"], [F.col("r.lote_utc").desc()])
    m = r.select(F.col("r.gkg_record_id").alias("gkg_record_id"), F.col("r.entidad").alias("entidad"),
                 F.to_timestamp("r.fecha_gdelt").alias("fecha_gdelt"), F.col("r.medio").alias("medio"),
                 F.col("r.url").alias("url"), F.col("r.tono").alias("tono"), F.col("r.formas").alias("formas"),
                 F.to_timestamp("r.lote_utc").alias("lote_utc"), "_archivo")
    n = publicar(m, f"{S}.gdelt_mencion", ["gkg_record_id", "entidad"],
                 "Menciones de entidades del universo en noticias (GDELT GKG), una por documento y entidad. "
                 "Datos: The GDELT Project (https://www.gdeltproject.org/).",
                 {"entidad": "Clave del diccionario producers/gcp_gdelt/alias.json.",
                  "tono": "Tono promedio del documento (V2Tone, primer valor)."},
                 borrar_faltantes=False)   # el respaldo de GCP vence a los 60 días; Silver conserva la historia
    return q, n


def main():
    q_gleif = gleif()
    n_lei = gleif_lei_valido()
    resumen = {"gleif_cuarentena": q_gleif, "gleif_lei": n_lei,
               "sec_edgar": sec_edgar(), "opensanctions": opensanctions(), "wikidata": wikidata(), "gdelt": gdelt()}
    print("silver (cuarentena, filas...): " + json.dumps(resumen))


main()
