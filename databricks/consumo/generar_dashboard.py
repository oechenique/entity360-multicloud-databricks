"""Genera entity360.lvdash.json, el dashboard AI/BI "Entity 360" (fase 10, regla 12).

El JSON de Lakeview es verboso (cada columna de tabla lleva ~20 propiedades): se escribe desde estas
definiciones y se versiona el resultado, que despliega Terraform (infra/databricks/consumo.tf).

Páginas:
1. Entity 360: buscador de empresa -> golden record con la procedencia de cada atributo, fuentes,
   duplicados resueltos (y casos en revisión), historial de cambios del CDC, señales de GDELT y riesgo
   de OpenSanctions.
2. Panorama: la plataforma entera (entidades, duplicados resueltos, noticias, riesgo, cambios).
3. Salud de la plataforma: frescura y volumen por fuente, cuarentenas, tests de dbt, resolución de
   identidades (decisiones, revisión, precisión y recall) y latencia de punta a punta.

Uso: python databricks/consumo/generar_dashboard.py
"""

import json
from pathlib import Path

SALIDA = Path(__file__).resolve().parent / "entity360.lvdash.json"
C = "entity360"
ENTIDAD = "regexp_extract(:empresa, '(E[0-9A-F]{12}(-[0-9]+)?)$', 1)"   # "<nombre> · <entity_id>"
EMPRESA_INICIAL = "BANCO MACRO SOCIEDAD ANONIMA · EEC00D3885F81"

# ------------------------------------------------------------------ datasets

DATASETS: dict[str, tuple[str, str]] = {
    # --- página 1: una empresa
    "buscador": ("Buscador de empresas", f"""
SELECT concat(nombre, ' · ', entity_id) AS empresa, nombre, pais, registros
FROM {C}.gold.dim_entity"""),
    "ficha": ("Golden record", f"""
SELECT orden, atributo, valor, procedencia FROM (
  SELECT stack(13,
    1, 'Nombre', nombre, procedencia['nombre'],
    2, 'País', pais, procedencia['pais'],
    3, 'Ciudad', ciudad, procedencia['ciudad'],
    4, 'LEI', lei, procedencia['lei'],
    5, 'CIK (SEC)', cast(cik AS string), procedencia['cik'],
    6, 'Ticker', ticker, procedencia['ticker'],
    7, 'Sitio web', sitio_web, procedencia['sitio_web'],
    8, 'Forma jurídica', forma_juridica, procedencia['forma_juridica'],
    9, 'Estado de la entidad (GLEIF)', estado_entidad, procedencia['estado_entidad'],
    10, 'Estado del LEI (GLEIF)', estado_registro, procedencia['estado_registro'],
    11, 'Sancionada', CASE WHEN sancionada THEN 'sí' ELSE 'no' END, 'opensanctions',
    12, 'En listas de riesgo', CASE WHEN en_listas_de_riesgo THEN 'sí' ELSE 'no' END, 'opensanctions',
    13, 'entity_id', entity_id, registro_ancla
  ) AS (orden, atributo, valor, procedencia)
  FROM {C}.gold.dim_entity WHERE entity_id = {ENTIDAD})
ORDER BY orden"""),
    "resumen_entidad": ("Resumen de la empresa", f"""
SELECT d.registros, size(d.fuentes) AS fuentes, d.duplicados_en_gleif,
       coalesce((SELECT sum(menciones) FROM {C}.gold.fct_news_signal n
                 WHERE n.entity_id = d.entity_id AND n.fecha >= date_sub(current_date(), 30)), 0) AS menciones_30d,
       (SELECT count(*) FROM {C}.gold.fct_risk_flags r WHERE r.entity_id = d.entity_id) AS listas_de_riesgo
FROM {C}.gold.dim_entity d WHERE d.entity_id = {ENTIDAD}"""),
    "fuentes": ("Fuentes de la empresa", f"""
SELECT fuente, id_fuente, nombre_en_fuente, CASE WHEN es_ancla THEN 'ancla' ELSE '' END AS rol, registro
FROM {C}.gold.bridge_entity_source WHERE entity_id = {ENTIDAD}
ORDER BY es_ancla DESC, fuente, registro"""),
    "duplicados": ("Duplicados resueltos", f"""
SELECT p.clave_a AS registro_a, ra.nombre AS nombre_a, p.clave_b AS registro_b, rb.nombre AS nombre_b,
       p.decision, p.puntaje, p.similitud_nombre, to_json(p.contribuciones) AS contribuciones,
       coalesce(p.motivo, '') AS motivo
FROM {C}.resolution.par_candidato p
JOIN {C}.resolution.entidad_registro ea ON ea.clave = p.clave_a
JOIN {C}.resolution.entidad_registro eb ON eb.clave = p.clave_b
JOIN {C}.resolution.registro ra ON ra.clave = p.clave_a
JOIN {C}.resolution.registro rb ON rb.clave = p.clave_b
WHERE ea.entity_id = {ENTIDAD} AND eb.entity_id = {ENTIDAD}
  AND p.decision IN ('determinístico', 'aceptado')
ORDER BY p.decision DESC, p.puntaje DESC"""),
    "revision_entidad": ("Casos en revisión de la empresa", f"""
SELECT v.tipo, v.puntaje, v.clave_a AS registro_a, ra.nombre AS nombre_a, v.clave_b AS registro_b,
       rb.nombre AS nombre_b, v.motivo
FROM {C}.resolution.revision v
JOIN {C}.resolution.entidad_registro ea ON ea.clave = v.clave_a
JOIN {C}.resolution.entidad_registro eb ON eb.clave = v.clave_b
JOIN {C}.resolution.registro ra ON ra.clave = v.clave_a
JOIN {C}.resolution.registro rb ON rb.clave = v.clave_b
WHERE {ENTIDAD} IN (ea.entity_id, eb.entity_id)
ORDER BY v.puntaje DESC"""),
    "cambios": ("Historial de cambios (CDC)", f"""
SELECT valido_desde, tabla_legacy, operacion, CASE WHEN vigente THEN 'vigente' ELSE 'histórica' END AS version,
       valido_hasta, detalle
FROM {C}.gold.fct_entity_changes WHERE entity_id = {ENTIDAD}
ORDER BY valido_desde DESC, tabla_legacy"""),
    "noticias": ("Señales de noticias (GDELT)", f"""
SELECT fecha, menciones, medios, tono_promedio, menciones_negativas
FROM {C}.gold.fct_news_signal WHERE entity_id = {ENTIDAD}"""),
    "riesgo": ("Riesgo (OpenSanctions)", f"""
SELECT nombre_en_lista, esquema, CASE WHEN sancionada THEN 'sí' ELSE 'no' END AS sancionada,
       sanciones, array_join(datasets, ', ') AS listas, array_join(paises, ', ') AS paises,
       CASE WHEN lei_coincide THEN 'LEI' ELSE 'nombre' END AS vinculo, primera_vez, ultimo_cambio
FROM {C}.gold.fct_risk_flags WHERE entity_id = {ENTIDAD}"""),

    # --- página 2: panorama
    "panorama": ("Panorama", f"""
SELECT count(*) AS entidades,
       count_if(registros > 1) AS con_varias_fuentes_o_registros,
       sum(registros) - count(*) AS registros_fusionados,
       sum(duplicados_en_gleif) AS duplicados_en_gleif,
       count_if(en_listas_de_riesgo) AS en_listas_de_riesgo,
       count_if(sancionada) AS sancionadas
FROM {C}.gold.dim_entity"""),
    "por_fuentes": ("Entidades por cantidad de fuentes", f"""
SELECT cast(size(fuentes) AS string) AS fuentes, count(*) AS entidades
FROM {C}.gold.dim_entity GROUP BY 1 ORDER BY 1"""),
    "mas_consolidadas": ("Entidades más consolidadas", f"""
SELECT d.nombre, d.pais, d.registros, array_join(d.fuentes, ', ') AS fuentes, d.duplicados_en_gleif, d.entity_id
FROM {C}.gold.dim_entity d WHERE d.registros > 1
ORDER BY d.registros DESC, size(d.fuentes) DESC, d.nombre"""),
    "noticias_recientes": ("Noticias recientes", f"""
SELECT d.nombre, sum(n.menciones) AS menciones, sum(n.menciones_negativas) AS negativas,
       round(sum(n.tono_promedio * n.menciones) / sum(n.menciones), 2) AS tono, max(n.fecha) AS ultima
FROM {C}.gold.fct_news_signal n JOIN {C}.gold.dim_entity d USING (entity_id)
WHERE n.fecha >= date_sub(current_date(), 30)
GROUP BY d.nombre ORDER BY menciones DESC"""),
    "alertas_riesgo": ("Alertas de riesgo", f"""
SELECT d.nombre, d.pais, r.nombre_en_lista, CASE WHEN r.sancionada THEN 'sí' ELSE 'no' END AS sancionada,
       array_join(r.datasets, ', ') AS listas, CASE WHEN r.lei_coincide THEN 'LEI' ELSE 'nombre' END AS vinculo
FROM {C}.gold.fct_risk_flags r JOIN {C}.gold.dim_entity d USING (entity_id)
ORDER BY r.sancionada DESC, d.nombre"""),
    "cambios_recientes": ("Cambios recientes del legacy", f"""
SELECT c.valido_desde, d.nombre, c.tabla_legacy, c.operacion, c.detalle
FROM {C}.gold.fct_entity_changes c LEFT JOIN {C}.gold.dim_entity d USING (entity_id)
WHERE c.operacion <> 'insert' OR c.valido_desde >= date_sub(current_date(), 7)
ORDER BY c.valido_desde DESC LIMIT 500"""),

    # --- página 3: salud de la plataforma
    "frescura": ("Frescura por fuente", f"""
WITH lotes AS (
  SELECT fuente, max(aterrizado_utc) AS ultimo_lote FROM {C}.ops.ingestion_log
  WHERE estado = 'ingerido_bronze' GROUP BY fuente
  UNION ALL
  SELECT 'resolucion', max(corrida_utc) FROM {C}.resolution.golden_record),
dbt AS (
  SELECT regexp_extract(nodo, '(lotes_)?([a-z_]+)$', 2) AS fuente, estado, ejecutado_utc,
         row_number() OVER (PARTITION BY nodo ORDER BY ejecutado_utc DESC) AS n
  FROM {C}.ops.dbt_resultado WHERE tipo = 'source' AND comando = 'freshness')
SELECT l.fuente, l.ultimo_lote,
       round((unix_timestamp(current_timestamp()) - unix_timestamp(l.ultimo_lote)) / 3600, 1) AS horas,
       coalesce(max(d.estado), 'sin medir') AS estado_dbt, max(d.ejecutado_utc) AS medido_utc
FROM lotes l
LEFT JOIN dbt d ON d.n = 1 AND (d.fuente = l.fuente OR (l.fuente = 'resolucion' AND d.fuente = 'golden_record'))
GROUP BY l.fuente, l.ultimo_lote ORDER BY l.fuente"""),
    "volumen": ("Volumen por fuente", f"""
SELECT date(aterrizado_utc) AS dia, fuente, count(*) AS lotes, sum(registros) AS registros
FROM {C}.ops.ingestion_log GROUP BY ALL"""),
    "lotes_no_ingeridos": ("Lotes en cuarentena o descartados", f"""
SELECT aterrizado_utc, fuente, estado, registros, archivo
FROM {C}.ops.ingestion_log WHERE estado <> 'ingerido_bronze'
ORDER BY aterrizado_utc DESC"""),
    "cuarentena_filas": ("Filas en cuarentena (Silver)", f"""
SELECT fuente, regexp_replace(motivo, ':.*$', '') AS motivo,
       CASE WHEN bloqueante THEN 'bloqueante' ELSE 'descartado el dato' END AS efecto,
       count(*) AS filas, max(detectado_utc) AS ultima
FROM {C}.silver._quarantine GROUP BY ALL ORDER BY filas DESC"""),
    "dbt_ultimo": ("Último resultado de cada nodo de dbt", f"""
SELECT nodo, tipo, estado, fallas, comando, ejecutado_utc, mensaje FROM (
  SELECT *, row_number() OVER (PARTITION BY nodo ORDER BY ejecutado_utc DESC) AS n
  FROM {C}.ops.dbt_resultado WHERE tipo IN ('model', 'test'))
WHERE n = 1"""),
    "dbt_resumen": ("Tests de dbt", f"""
SELECT count_if(tipo = 'test' AND estado = 'pass') AS tests_ok,
       count_if(tipo = 'test' AND estado <> 'pass') AS tests_con_problemas,
       count_if(tipo = 'model' AND estado = 'success') AS modelos_ok,
       count_if(tipo = 'model' AND estado <> 'success') AS modelos_con_error,
       max(ejecutado_utc) AS ultima_corrida
FROM (SELECT *, row_number() OVER (PARTITION BY nodo ORDER BY ejecutado_utc DESC) AS n
      FROM {C}.ops.dbt_resultado WHERE tipo IN ('model', 'test'))
WHERE n = 1"""),
    "decisiones": ("Decisiones de la resolución", f"""
SELECT decision, count(*) AS pares FROM {C}.resolution.par_candidato GROUP BY decision"""),
    "revision": ("Casos en revisión", f"""
SELECT tipo, count(*) AS casos FROM {C}.resolution.revision GROUP BY tipo"""),
    "calidad": ("Precisión y recall de la resolución", f"""
SELECT version, particion, CASE WHEN ciega THEN 'sí' ELSE 'no' END AS ciega, vp, fp, fn,
       concat(format_number(precision, 3), '  [', format_number(precision_ic_inf, 3), ' – ',
              format_number(precision_ic_sup, 3), ']') AS precision_ic95,
       concat(format_number(recall, 3), '  [', format_number(recall_ic_inf, 3), ' – ',
              format_number(recall_ic_sup, 3), ']') AS recall_ic95,
       entidades
FROM {C}.ops.calidad_resolucion ORDER BY version, particion DESC"""),
    "latencia": ("Latencia de punta a punta", f"""
WITH bronze AS (
  SELECT _sha256 AS sha256, min(_ingerido_utc) AS bronze_utc FROM {C}.bronze.gdelt GROUP BY 1 UNION ALL
  SELECT _sha256, min(_ingerido_utc) FROM {C}.bronze.opensanctions GROUP BY 1 UNION ALL
  SELECT _sha256, min(_ingerido_utc) FROM {C}.bronze.sec_edgar GROUP BY 1 UNION ALL
  SELECT _sha256, min(_ingerido_utc) FROM {C}.bronze.sqlserver_cdc GROUP BY 1 UNION ALL
  SELECT _sha256, min(_ingerido_utc) FROM {C}.bronze.wikidata GROUP BY 1),
ultimo AS (
  SELECT l.*, row_number() OVER (PARTITION BY fuente ORDER BY aterrizado_utc DESC) AS n
  FROM {C}.ops.ingestion_log l WHERE estado = 'ingerido_bronze'),
res AS (SELECT max(corrida_utc) AS resolucion_utc FROM {C}.resolution.golden_record)
SELECT u.fuente, u.extraido_utc, b.bronze_utc, r.resolucion_utc,
       round((unix_timestamp(u.aterrizado_utc) - unix_timestamp(u.extraido_utc)) / 60, 1) AS min_hasta_landing,
       round((unix_timestamp(b.bronze_utc) - unix_timestamp(u.extraido_utc)) / 60, 1) AS min_hasta_bronze,
       round((unix_timestamp(r.resolucion_utc) - unix_timestamp(u.extraido_utc)) / 60, 1) AS min_hasta_golden
FROM ultimo u LEFT JOIN bronze b USING (sha256) CROSS JOIN res r
WHERE u.n = 1 ORDER BY u.fuente"""),
}
CON_EMPRESA = {"ficha", "resumen_entidad", "fuentes", "duplicados", "revision_entidad", "cambios", "noticias",
               "riesgo"}


def dataset(nombre: str) -> dict:
    titulo, sql = DATASETS[nombre]
    d = {"name": nombre, "displayName": titulo, "queryLines": [l + "\n" for l in sql.strip().split("\n")]}
    if nombre in CON_EMPRESA:
        d["parameters"] = [{"displayName": "empresa", "keyword": "empresa", "dataType": "STRING",
                            "defaultSelection": {"values": {"dataType": "STRING",
                                                            "values": [{"value": EMPRESA_INICIAL}]}}}]
    return d


# ------------------------------------------------------------------ widgets

_n = 0


def _nombre(prefijo: str) -> str:
    global _n
    _n += 1
    return f"{prefijo}_{_n:02d}"


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def texto(lineas: list[str], p: dict) -> dict:
    return {"widget": {"name": _nombre("texto"), "multilineTextboxSpec": {"lines": lineas}}, "position": p}


def _frame(titulo: str, descripcion: str | None = None) -> dict:
    f = {"showTitle": True, "title": titulo}
    if descripcion:
        f |= {"showDescription": True, "description": descripcion}
    return f


def tabla(ds: str, columnas: list[tuple[str, str, str]], titulo: str, p: dict, descripcion: str | None = None) -> dict:
    """columnas: (campo, título, tipo: string | number | float | datetime | date)."""
    cols = []
    for i, (campo, tit, tipo) in enumerate(columnas):
        c = {"fieldName": campo, "booleanValues": ["false", "true"], "imageUrlTemplate": "{{ @ }}",
             "imageTitleTemplate": "{{ @ }}", "imageWidth": "", "imageHeight": "", "linkUrlTemplate": "{{ @ }}",
             "linkTextTemplate": "{{ @ }}", "linkTitleTemplate": "{{ @ }}", "linkOpenInNewTab": True,
             "type": {"number": "integer", "float": "float"}.get(tipo, tipo),
             "displayAs": {"number": "number", "float": "number"}.get(tipo, tipo),
             "visible": True, "order": 100000 + i, "title": tit, "allowSearch": tipo == "string",
             "alignContent": "right" if tipo in ("number", "float") else "left", "allowHTML": False,
             "highlightLinks": False, "useMonospaceFont": False, "preserveWhitespace": False, "displayName": tit}
        if tipo == "number":
            c["numberFormat"] = "0"
        if tipo == "float":
            c["numberFormat"] = "0.00"
        if tipo == "datetime":
            c["dateTimeFormat"] = "YYYY-MM-DD HH:mm"
        if tipo == "date":
            c["type"], c["displayAs"], c["dateTimeFormat"] = "datetime", "datetime", "YYYY-MM-DD"
        cols.append(c)
    return {"widget": {"name": _nombre("tabla"),
                       "queries": [{"name": "main_query", "query": {
                           "datasetName": ds, "disaggregated": True,
                           "fields": [{"name": c, "expression": f"`{c}`"} for c, _, _ in columnas]}}],
                       "spec": {"version": 1, "widgetType": "table", "allowHTMLByDefault": False, "condensed": True,
                                "withRowNumber": False, "encodings": {"columns": cols},
                                "invisibleColumns": [], "itemsPerPage": 25, "paginationSize": "default",
                                "frame": _frame(titulo, descripcion)}},
            "position": p}


def contador(ds: str, campo: str, titulo: str, p: dict, descripcion: str | None = None) -> dict:
    return {"widget": {"name": _nombre("contador"),
                       "queries": [{"name": "main_query", "query": {
                           "datasetName": ds, "disaggregated": False,
                           "fields": [{"name": f"sum({campo})", "expression": f"SUM(`{campo}`)"}]}}],
                       "spec": {"version": 2, "widgetType": "counter",
                                "encodings": {"value": {"fieldName": f"sum({campo})", "displayName": titulo}},
                                "frame": _frame(titulo, descripcion)}},
            "position": p}


def barras(ds: str, x: str, y: str, titulo: str, p: dict, color: str | None = None, x_tipo="categorical",
           x_titulo: str | None = None, y_titulo: str | None = None, descripcion: str | None = None,
           tipo="bar") -> dict:
    campos = [{"name": x, "expression": f"`{x}`"}, {"name": f"sum({y})", "expression": f"SUM(`{y}`)"}]
    enc = {"x": {"fieldName": x, "scale": {"type": x_tipo}, "displayName": x_titulo or x},
           "y": {"fieldName": f"sum({y})", "scale": {"type": "quantitative"}, "displayName": y_titulo or y},
           "label": {"show": tipo == "bar"}}
    if color:
        campos.append({"name": color, "expression": f"`{color}`"})
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color}
    return {"widget": {"name": _nombre(tipo),
                       "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False,
                                                                     "fields": campos}}],
                       "spec": {"version": 3, "widgetType": tipo, "encodings": enc,
                                "frame": _frame(titulo, descripcion)}},
            "position": p}


def buscador(p: dict) -> dict:
    """Selector de empresa: sus valores salen de `buscador` y fija el parámetro `empresa` de los datasets."""
    queries = [{"name": "valores_buscador_empresa", "query": {
        "datasetName": "buscador", "disaggregated": False,
        "fields": [{"name": "empresa", "expression": "`empresa`"},
                   {"name": "empresa_associativity", "expression": "COUNT_IF(`associative_filter_predicate_group`)"}]}}]
    campos = [{"fieldName": "empresa", "displayName": "Empresa", "queryName": "valores_buscador_empresa"}]
    for ds in sorted(CON_EMPRESA):
        q = f"parametro_{ds}_empresa"
        queries.append({"name": q, "query": {"datasetName": ds, "parameters": [{"name": "empresa", "keyword": "empresa"}],
                                             "disaggregated": False}})
        campos.append({"parameterName": "empresa", "queryName": q})
    return {"widget": {"name": "buscador_empresa", "queries": queries,
                       "spec": {"version": 2, "widgetType": "filter-single-select",
                                "encodings": {"fields": campos},
                                "frame": _frame("Empresa", "Escribí parte del nombre: la lista busca entre las "
                                                           "1.136 entidades del golden record.")}},
            "position": p}


# ------------------------------------------------------------------ páginas

def pagina_entidad() -> dict:
    return {"name": "entity360", "displayName": "Entity 360", "pageType": "PAGE_TYPE_CANVAS", "layout": [
        texto(["## Entity 360",
               "Una fila confiable por empresa, consolidada desde GLEIF (el legacy, por CDC), SEC EDGAR, "
               "OpenSanctions, Wikidata y GDELT. Elegí una empresa: cada atributo dice de qué registro sale."],
              pos(0, 0, 6, 2)),
        buscador(pos(0, 2, 3, 2)),
        contador("resumen_entidad", "registros", "Registros unidos", pos(3, 2, 1, 2)),
        contador("resumen_entidad", "fuentes", "Fuentes", pos(4, 2, 1, 2)),
        contador("resumen_entidad", "menciones_30d", "Menciones (30 días)", pos(5, 2, 1, 2)),
        tabla("ficha", [("atributo", "Atributo", "string"), ("valor", "Valor", "string"),
                        ("procedencia", "Sale de", "string")],
              "Golden record", pos(0, 4, 3, 9),
              "Reglas de supervivencia por atributo (GLEIF > SEC > Wikidata > OpenSanctions > GDELT)."),
        tabla("fuentes", [("fuente", "Fuente", "string"), ("id_fuente", "Id en la fuente", "string"),
                          ("nombre_en_fuente", "Nombre en la fuente", "string"), ("rol", "Rol", "string")],
              "Fuentes de las que sale", pos(3, 4, 3, 5)),
        tabla("riesgo", [("nombre_en_lista", "Nombre en la lista", "string"), ("sancionada", "Sancionada", "string"),
                         ("listas", "Listas", "string"), ("vinculo", "Vínculo", "string"),
                         ("sanciones", "Sanciones", "string")],
              "Riesgo (OpenSanctions)", pos(3, 9, 3, 4),
              "Datos: OpenSanctions (opensanctions.org), CC BY-NC 4.0. Vacío = no figura en listas."),
        tabla("duplicados", [("registro_a", "Registro A", "string"), ("nombre_a", "Nombre A", "string"),
                             ("registro_b", "Registro B", "string"), ("nombre_b", "Nombre B", "string"),
                             ("decision", "Decisión", "string"), ("puntaje", "Puntaje", "number"),
                             ("contribuciones", "Señales", "string"), ("motivo", "Motivo", "string")],
              "Duplicados resueltos", pos(0, 13, 6, 6),
              "Pares que la resolución unió: determinístico (LEI o CIK compartido) o aceptado por puntaje "
              "(umbral 70), con la contribución de cada señal."),
        tabla("revision_entidad", [("tipo", "Tipo", "string"), ("puntaje", "Puntaje", "number"),
                                   ("registro_a", "Registro A", "string"), ("nombre_a", "Nombre A", "string"),
                                   ("registro_b", "Registro B", "string"), ("nombre_b", "Nombre B", "string"),
                                   ("motivo", "Motivo", "string")],
              "Casos en revisión que la tocan", pos(0, 19, 6, 4),
              "Lo que la resolución no fuerza: puntaje entre 50 y 69, conflictos y empates."),
        barras("noticias", "fecha", "menciones", "Menciones en noticias por día (GDELT)", pos(0, 23, 3, 6),
               x_tipo="temporal", x_titulo="Día", y_titulo="Menciones",
               descripcion="Datos: The GDELT Project (gdeltproject.org)."),
        tabla("noticias", [("fecha", "Día", "date"), ("menciones", "Menciones", "number"),
                           ("medios", "Medios", "number"), ("tono_promedio", "Tono", "float"),
                           ("menciones_negativas", "Negativas", "number")],
              "Tono de la cobertura", pos(3, 23, 3, 6), "Tono V2Tone de GDELT: negativo = cobertura negativa."),
        tabla("cambios", [("valido_desde", "Desde", "datetime"), ("tabla_legacy", "Tabla del legacy", "string"),
                          ("operacion", "Operación", "string"), ("version", "Versión", "string"),
                          ("detalle", "Detalle", "string")],
              "Historial de cambios (CDC del legacy)", pos(0, 29, 6, 7),
              "Cada versión de las filas del ERP legacy (SQL Server) que capturó el CDC."),
    ]}


def pagina_panorama() -> dict:
    return {"name": "panorama", "displayName": "Panorama", "pageType": "PAGE_TYPE_CANVAS", "layout": [
        contador("panorama", "entidades", "Entidades (golden records)", pos(0, 0, 1, 2)),
        contador("panorama", "registros_fusionados", "Registros fusionados", pos(1, 0, 1, 2),
                 "Registros de más que la resolución unió a otra entidad."),
        contador("panorama", "con_varias_fuentes_o_registros", "Entidades consolidadas", pos(2, 0, 1, 2),
                 "Entidades con más de un registro."),
        contador("panorama", "duplicados_en_gleif", "LEI duplicados fusionados", pos(3, 0, 1, 2)),
        contador("panorama", "en_listas_de_riesgo", "En listas de riesgo", pos(4, 0, 1, 2)),
        contador("panorama", "sancionadas", "Sancionadas", pos(5, 0, 1, 2)),
        barras("por_fuentes", "fuentes", "entidades", "Entidades por cantidad de fuentes", pos(0, 2, 2, 6),
               x_titulo="Fuentes", y_titulo="Entidades"),
        tabla("mas_consolidadas", [("nombre", "Entidad", "string"), ("pais", "País", "string"),
                                   ("registros", "Registros", "number"), ("fuentes", "Fuentes", "string"),
                                   ("duplicados_en_gleif", "LEI duplicados", "number")],
              "Duplicados resueltos: entidades más consolidadas", pos(2, 2, 4, 6)),
        tabla("noticias_recientes", [("nombre", "Entidad", "string"), ("menciones", "Menciones", "number"),
                                     ("negativas", "Negativas", "number"), ("tono", "Tono", "float"),
                                     ("ultima", "Última", "date")],
              "Señales de noticias (30 días)", pos(0, 8, 3, 6), "Datos: The GDELT Project."),
        tabla("alertas_riesgo", [("nombre", "Entidad", "string"), ("sancionada", "Sancionada", "string"),
                                 ("listas", "Listas", "string"), ("vinculo", "Vínculo", "string")],
              "Alertas de riesgo", pos(3, 8, 3, 6), "Datos: OpenSanctions, CC BY-NC 4.0."),
        tabla("cambios_recientes", [("valido_desde", "Desde", "datetime"), ("nombre", "Entidad", "string"),
                                    ("tabla_legacy", "Tabla", "string"), ("operacion", "Operación", "string"),
                                    ("detalle", "Detalle", "string")],
              "Cambios recientes del legacy (CDC)", pos(0, 14, 6, 6),
              "Updates y deletes, más los inserts de los últimos 7 días."),
    ]}


def pagina_salud() -> dict:
    return {"name": "salud", "displayName": "Salud de la plataforma", "pageType": "PAGE_TYPE_CANVAS", "layout": [
        texto(["## Salud de la plataforma",
               "Frescura y volumen por fuente, cuarentenas, tests de dbt y calidad de la resolución de "
               "identidades. El estado de frescura es el de la última corrida de `dbt source freshness`."],
              pos(0, 0, 6, 2)),
        tabla("frescura", [("fuente", "Fuente", "string"), ("ultimo_lote", "Último lote ingerido", "datetime"),
                           ("horas", "Horas", "float"), ("estado_dbt", "dbt freshness", "string"),
                           ("medido_utc", "Medido", "datetime")],
              "Frescura por fuente", pos(0, 2, 3, 5)),
        tabla("latencia", [("fuente", "Fuente", "string"), ("extraido_utc", "Extraído", "datetime"),
                           ("min_hasta_landing", "→ landing (min)", "float"),
                           ("min_hasta_bronze", "→ Bronze (min)", "float"),
                           ("min_hasta_golden", "→ golden (min)", "float")],
              "Latencia de punta a punta (último lote)", pos(3, 2, 3, 5),
              "Minutos desde la extracción en la fuente hasta cada capa. Golden: última corrida de la "
              "resolución (negativo = el lote llegó después)."),
        barras("volumen", "dia", "registros", "Registros aterrizados por día", pos(0, 7, 3, 6), color="fuente",
               x_tipo="temporal", x_titulo="Día", y_titulo="Registros"),
        barras("volumen", "dia", "lotes", "Lotes por día", pos(3, 7, 3, 6), color="fuente", x_tipo="temporal",
               x_titulo="Día", y_titulo="Lotes"),
        tabla("lotes_no_ingeridos", [("aterrizado_utc", "Aterrizó", "datetime"), ("fuente", "Fuente", "string"),
                                     ("estado", "Estado", "string"), ("registros", "Registros", "number"),
                                     ("archivo", "Archivo", "string")],
              "Lotes en cuarentena o descartados", pos(0, 13, 3, 5),
              "cuarentena_contrato: el contrato de llegada (Soda) lo rechazó; duplicado: sha256 ya ingerido."),
        tabla("cuarentena_filas", [("fuente", "Fuente", "string"), ("motivo", "Motivo", "string"),
                                   ("efecto", "Efecto", "string"), ("filas", "Filas", "number"),
                                   ("ultima", "Última", "datetime")],
              "Filas en cuarentena (Silver)", pos(3, 13, 3, 5)),
        contador("dbt_resumen", "tests_ok", "Tests de dbt en verde", pos(0, 18, 1, 2)),
        contador("dbt_resumen", "tests_con_problemas", "Tests con fallas o avisos", pos(1, 18, 1, 2)),
        contador("dbt_resumen", "modelos_ok", "Modelos Gold construidos", pos(0, 20, 1, 2)),
        contador("dbt_resumen", "modelos_con_error", "Modelos con error", pos(1, 20, 1, 2)),
        texto(["Último resultado de cada nodo, a mano o desde Airflow (hook `on-run-end` de dbt → "
               "`ops.dbt_resultado`)."], pos(0, 22, 2, 1)),
        tabla("dbt_ultimo", [("nodo", "Nodo", "string"), ("tipo", "Tipo", "string"), ("estado", "Estado", "string"),
                             ("fallas", "Fallas", "number"), ("ejecutado_utc", "Ejecutado", "datetime")],
              "Último resultado de cada modelo y test de dbt", pos(2, 18, 4, 5)),
        barras("decisiones", "decision", "pares", "Decisiones de la resolución (pares)", pos(0, 23, 3, 5),
               x_titulo="Decisión", y_titulo="Pares"),
        barras("revision", "tipo", "casos", "Casos en revisión", pos(3, 23, 3, 5), x_titulo="Tipo",
               y_titulo="Casos", descripcion="revisar: puntaje 50–69; conflicto: uniría dos LEI firmes o dos "
                                             "CIK; empate: mismo puntaje con LEI firmes distintos."),
        tabla("calidad", [("version", "Versión", "string"), ("particion", "Partición", "string"),
                          ("ciega", "Ciega", "string"), ("vp", "VP", "number"), ("fp", "FP", "number"),
                          ("fn", "FN", "number"), ("precision_ic95", "Precisión [IC 95 %]", "string"),
                          ("recall_ic95", "Recall [IC 95 %]", "string"), ("entidades", "Entidades", "number")],
              "Precisión y recall contra el set curado a mano", pos(0, 28, 6, 5),
              "Wilson al 95 %. Solo la v1 se midió a ciegas; v2 y v2.1 miraron los errores del set completo."),
    ]}


def main():
    paginas = [pagina_entidad(), pagina_panorama(), pagina_salud()]
    usados = {q["query"]["datasetName"] for p in paginas for l in p["layout"] for q in l["widget"].get("queries", [])}
    faltan = usados - set(DATASETS)
    assert not faltan, faltan
    d = {"datasets": [dataset(n) for n in DATASETS if n in usados], "pages": paginas,
         "uiSettings": {"theme": {"widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED"}, "applyModeEnabled": False}}
    SALIDA.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{SALIDA.name}: {len(d['datasets'])} datasets, {sum(len(p['layout']) for p in paginas)} widgets")


if __name__ == "__main__":
    main()
