"""Tarea `resolucion` del job entity360-medallion (regla 08, ADR 0004): de Silver a entidades.

1. Registros: GLEIF (el legacy, vigente), SEC EDGAR, OpenSanctions del universo, Wikidata y las
   claves del diccionario de alias de GDELT, con la misma clave que el set de validación.
2. Blocking (identidades.pares_candidatos) más los pares que comparten LEI o CIK.
3. Score por reglas (identidades.puntuar) distribuido con mapInPandas.
4. Clusters con restricciones y entity_id estable (se conserva el de la corrida anterior).
5. Golden record por reglas de supervivencia.

Tablas (schema resolution, Iceberg gestionado, escritas con MERGE):
    registro, par_candidato, revision, entidad_registro, golden_record.

El universo es chico (~1.300 registros): el blocking y los clusters corren en el driver. Con un
universo grande, las claves de bloqueo se explotan y se cruzan en Spark, y los clusters se hacen
con componentes conexas distribuidas; el score ya corre distribuido.

El LEI que alias.json trae para algunas claves de GDELT **no se usa**: es una anotación manual de la
fase 4, y usarla metería decisiones humanas en el matching que después se evalúa contra ellas.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import comun

spark = comun.spark_y_modulos()

import pandas as pd  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

import identidades as I  # noqa: E402
import normalizacion as N  # noqa: E402

S = f"{comun.CATALOGO}.silver"
R = f"{comun.CATALOGO}.resolution"
# El script de la tarea no tiene __file__ (spark_python_task lo corre con exec): la ruta sale de comun.
ALIAS = Path(comun.__file__).resolve().parent / "alias.json"


def filas(sql: str) -> list[dict]:
    return [r.asDict(recursive=True) for r in spark.sql(sql).collect()]


def host(url: str | None) -> str | None:
    if not url:
        return None
    h = re.sub(r"^[a-z]+://", "", url.strip().lower()).split("/")[0]
    return re.sub(r"^www\.", "", h) or None


def registro(fuente, id_fuente, nombres, paises=(), ciudad=None, leis=(), ciks=(), tickers=(), dominios=(),
             lei_firme=False, datos=None) -> dict:
    return {"clave": f"{fuente}:{id_fuente}", "fuente": fuente, "id_fuente": str(id_fuente),
            "nombres": [n for n in dict.fromkeys(nombres) if n], "paises": [p for p in dict.fromkeys(paises) if p],
            "ciudad": ciudad, "leis": sorted(set(leis)), "ciks": sorted({int(c) for c in ciks}),
            "tickers": sorted({t.upper() for t in tickers if t}), "dominios": sorted({d for d in dominios if d}),
            "lei_firme": lei_firme, "datos": datos or {}}


def registros() -> list[dict]:
    out = []
    for g in filas(f"""
            SELECT e.lei, e.nombre_legal, e.jurisdiccion, e.estado_registro, e.estado_entidad, e.forma_juridica,
                   l.lei_valido, first(d.ciudad, true) AS ciudad, collect_list(n.nombre) AS alternativos
            FROM {S}.gleif_entidad e
            JOIN {S}.gleif_lei l USING (lei)
            LEFT JOIN {S}.gleif_direccion d ON d.lei = e.lei AND d.tipo = 'SEDE'
            LEFT JOIN {S}.gleif_nombre_alternativo n ON n.lei = e.lei
            GROUP BY ALL"""):
        firme = bool(g["lei_valido"]) and g["estado_registro"] not in I.ESTADOS_NO_FIRMES
        out.append(registro("gleif", g["lei"], [g["nombre_legal"], *g["alternativos"]],
                            [N.pais(g["jurisdiccion"], "gleif")], N.ciudad(g["ciudad"]), [g["lei"]], lei_firme=firme,
                            datos={"forma_juridica": g["forma_juridica"] or None, "estado_entidad": g["estado_entidad"],
                                   "estado_registro": g["estado_registro"]}))
    for s in filas(f"""
            SELECT e.cik, e.nombre, e.ticker, e.tickers, e.pais_incorporacion, e.pais_sede, e.ciudad_sede,
                   e.sitio_web, e.forma_juridica,
                   collect_list(CASE WHEN n.tipo = 'anterior' THEN n.nombre END) AS anteriores
            FROM {S}.sec_emisor e LEFT JOIN {S}.sec_nombre n USING (cik) GROUP BY ALL"""):
        out.append(registro("sec_edgar", s["cik"], [s["nombre"], *s["anteriores"]],
                            [s["pais_incorporacion"], s["pais_sede"]], s["ciudad_sede"], ciks=[s["cik"]],
                            tickers=[s["ticker"], *(s["tickers"] or [])], dominios=[host(s["sitio_web"])],
                            datos={"sitio_web": s["sitio_web"], "forma_juridica": s["forma_juridica"] or None}))
    for o in filas(f"""SELECT id, nombre, aliases, paises, leis, sancionada, esquema, datasets
                       FROM {S}.opensanctions_entidad WHERE en_universo"""):
        out.append(registro("opensanctions", o["id"], [o["nombre"], *o["aliases"]], o["paises"], leis=o["leis"],
                            datos={"sancionada": o["sancionada"], "esquema": o["esquema"], "datasets": o["datasets"]}))
    for w in filas(f"""SELECT qid, etiqueta_es, etiqueta_en, leis, ciks, simbolos, paises, dominios, sitios_web
                       FROM {S}.wikidata_item"""):
        out.append(registro("wikidata", w["qid"], [w["etiqueta_es"], w["etiqueta_en"]], w["paises"], leis=w["leis"],
                            ciks=w["ciks"], tickers=w["simbolos"], dominios=w["dominios"],
                            datos={"sitio_web": (w["sitios_web"] or [None])[0]}))
    for e in json.loads(ALIAS.read_text(encoding="utf-8"))["entidades"]:
        nombre = re.sub(r"\s*\(.*\)\s*$", "", e["nombre"])          # "(subsidiaria de GGAL, ...)"
        # Sin país: el diccionario no lo dice y suponer AR sumaba puntos falsos (la clave VIST, de la
        # matriz mexicana, quedaba unida a la filial argentina; calibración v1, 2026-09-27). Lo hereda
        # del registro con el que comparte CIK (identidades.heredar_paises, v2.1).
        out.append(registro("gdelt", e["clave"], [nombre, *(a["forma"] for a in e["alias"])],
                            ciks=[e["cik"]] if e.get("cik") else []))
    return out


SALIDA_SCORE = ("clave_a string, clave_b string, bloques array<string>, puntaje int, similitud_nombre double, "
                "contribuciones string, decision string, motivo string")


def puntuar_todo(regs: list[dict], pares: dict[tuple[str, str], set[str]]) -> list[dict]:
    por_clave = {r["clave"]: r for r in regs}   # viaja en la clausura de la UDF (Spark Connect no tiene broadcast)

    def score(it):
        for pdf in it:
            out = []
            for x in pdf.itertuples():
                p = I.puntuar(por_clave[x.clave_a], por_clave[x.clave_b])
                out.append((x.clave_a, x.clave_b, list(x.bloques), p["puntaje"], p["similitud_nombre"],
                            json.dumps(p["contribuciones"]), p["decision"], p["motivo"]))
            # object: que un puntaje nulo (veto) llegue como null y no como NaN
            yield pd.DataFrame(out, columns=[c.split()[0] for c in SALIDA_SCORE.split(", ")], dtype=object)

    df = spark.createDataFrame([(a, b, sorted(bl)) for (a, b), bl in pares.items()],
                               "clave_a string, clave_b string, bloques array<string>")
    out = [r.asDict(recursive=True) for r in df.repartition(8).mapInPandas(score, SALIDA_SCORE).collect()]
    for p in out:
        p["contribuciones"] = json.loads(p["contribuciones"])
    return out


def previos() -> dict[str, str]:
    if not spark.catalog.tableExists(f"{R}.entidad_registro"):
        return {}
    return {r["clave"]: r["entity_id"] for r in filas(f"SELECT clave, entity_id FROM {R}.entidad_registro")}


def main():
    corrida = datetime.now(timezone.utc).replace(microsecond=0)
    regs = I.preparar(registros())
    pares, resumen_bloqueo = I.pares_candidatos(regs)
    for p in I.pares_por_identificador(regs):
        pares.setdefault(p, set()).add("identificador")
    puntuados = puntuar_todo(regs, pares)

    raices, conflictos = I.clusters(regs, puntuados)
    grupos: dict[str, list[dict]] = {}
    for r in regs:
        grupos.setdefault(raices[r["clave"]], []).append(r)
    ids = I.entity_ids(grupos, previos())
    goldens = [I.golden(ids[raiz], miembros) for raiz, miembros in grupos.items()]

    # ---------------------------------------------------------------- escritura
    reg_df = spark.createDataFrame(
        [(r["clave"], r["fuente"], r["id_fuente"], r["nombres"][0] if r["nombres"] else None, r["nombres"],
          r["paises"], r["ciudad"], r["leis"], r["lei_firme"], r["ciks"], r["tickers"], r["dominios"]) for r in regs],
        "clave string, fuente string, id_fuente string, nombre string, nombres array<string>, paises array<string>, "
        "ciudad string, leis array<string>, lei_firme boolean, ciks array<bigint>, tickers array<string>, "
        "dominios array<string>")
    comun.publicar(spark, reg_df, f"{R}.registro", ["clave"],
                   "Registros de todas las fuentes que entran a la resolución de identidades, con la clave "
                   "<fuente>:<id> que usa el set de validación.", "resolution",
                   {"clave": "<fuente>:<id>: gleif:<LEI>, sec_edgar:<CIK>, opensanctions:<id>, wikidata:<QID>, "
                             "gdelt:<clave de alias.json>.",
                    "lei_firme": "Solo GLEIF: dígito de control válido y registro no ANNULLED ni DUPLICATE.",
                    "paises": "Países ISO del registro. En GDELT, heredados del registro con el que comparte CIK o "
                              "LEI (vacío si no comparte ninguno)."})

    par_df = spark.createDataFrame(
        [(p["clave_a"], p["clave_b"], p["bloques"], p["puntaje"], p["similitud_nombre"], p["contribuciones"],
          p["decision"], p["motivo"]) for p in puntuados],
        SALIDA_SCORE.replace("contribuciones string", "contribuciones map<string,int>")
    ).withColumn("corrida_utc", F.lit(corrida))
    n_pares = comun.publicar(
        spark, par_df, f"{R}.par_candidato", ["clave_a", "clave_b"],
        "Pares de registros que el blocking juntó (o que comparten LEI/CIK), con su puntaje por reglas, la "
        "contribución de cada señal y la decisión. Pesos y umbrales iniciales, sin calibrar.", "resolution",
        {"decision": "determinístico | aceptado | revisar | rechazado | veto.",
         "contribuciones": "Puntos que aporta cada señal (identidades.PESOS).",
         "bloques": "Tipos de bloque que juntaron el par: pais_prefijo, token, ticker, dominio, identificador."})

    revision = [(p["clave_a"], p["clave_b"], p["puntaje"], p["decision"], p["motivo"])
                for p in puntuados if p["decision"] == "revisar"]
    revision += [(c["clave_a"], c["clave_b"], c["puntaje"],
                  "empate" if c["motivo"].startswith("empate") else "conflicto", c["motivo"]) for c in conflictos]
    rev_df = spark.createDataFrame(revision, "clave_a string, clave_b string, puntaje int, tipo string, motivo string")
    comun.publicar(spark, rev_df.withColumn("corrida_utc", F.lit(corrida)), f"{R}.revision", ["clave_a", "clave_b"],
                   "Casos que la resolución no fuerza (regla 08, paso 7): puntaje intermedio (revisar), un par "
                   "aceptado que uniría dos LEI firmes o dos CIK distintos (conflicto) o un empate en el mejor "
                   "puntaje con candidatos de LEI firmes distintos (empate).", "resolution")

    er = [(r["clave"], ids[raices[r["clave"]]]) for r in regs]
    comun.publicar(spark, spark.createDataFrame(er, "clave string, entity_id string")
                   .withColumn("corrida_utc", F.lit(corrida)), f"{R}.entidad_registro", ["clave"],
                   "A qué entidad pertenece cada registro. El entity_id es estable entre corridas: un cluster "
                   "conserva el id que tenían sus registros.", "resolution")

    gold_df = spark.createDataFrame(
        [(g["entity_id"], g["registro_ancla"], g["nombre"], g["pais"], g["ciudad"], g["lei"],
          int(g["cik"]) if g["cik"] is not None else None, g["ticker"], g["sitio_web"], g["forma_juridica"],
          g["estado_entidad"], g["estado_registro"], g["sancionada"], g["en_listas_de_riesgo"], g["fuentes"],
          g["registros"], g["duplicados_en_gleif"], g["procedencia"]) for g in goldens],
        "entity_id string, registro_ancla string, nombre string, pais string, ciudad string, lei string, cik bigint, "
        "ticker string, sitio_web string, forma_juridica string, estado_entidad string, estado_registro string, "
        "sancionada boolean, en_listas_de_riesgo boolean, fuentes array<string>, registros int, "
        "duplicados_en_gleif int, procedencia map<string,string>")
    comun.publicar(spark, gold_df.withColumn("corrida_utc", F.lit(corrida)), f"{R}.golden_record", ["entity_id"],
                   "Golden record: una fila por entidad, con reglas de supervivencia por atributo "
                   "(identidades.SUPERVIVENCIA). procedencia dice de qué registro sale cada atributo.", "resolution",
                   {"procedencia": "Atributo -> clave del registro del que sobrevive.",
                    "duplicados_en_gleif": "Registros de GLEIF de más en la entidad (LEI anulados o duplicados)."})

    decisiones = {}
    for p in puntuados:
        decisiones[p["decision"]] = decisiones.get(p["decision"], 0) + 1
    por_fuente = {}
    for r in regs:
        por_fuente[r["fuente"]] = por_fuente.get(r["fuente"], 0) + 1
    multi = sum(1 for m in grupos.values() if len(m) > 1)
    print(f"resolution.registro: {len(regs)} {json.dumps(por_fuente)}")
    print(f"blocking: {json.dumps(resumen_bloqueo)}; pares puntuados: {n_pares}")
    print(f"decisiones: {json.dumps(decisiones, ensure_ascii=False)}; conflictos: {len(conflictos)}")
    print(f"entidades: {len(grupos)} ({multi} con más de un registro)")


main()
