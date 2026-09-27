{#
  Post-hook de Gold: lo que dbt-databricks 1.12 no aplica sobre Iceberg gestionado.

  Con table_format iceberg, el adapter trata la tabla como parquet y se saltea las restricciones
  ("Constraints not supported for file format: parquet") y los comentarios de columna ("file format
  parquet does not support that"). Iceberg gestionado admite las dos cosas (verificado el 2026-09-27;
  Silver ya comenta columnas así):
  - NOT NULL: se aplica y el motor lo hace cumplir (un INSERT con nulo falla).
  - Comentarios de columna: las descripciones de dbt, que usa Genie (regla 12).
  PRIMARY KEY y CHECK no se admiten en Iceberg gestionado: van como tests de dbt. ADR 0005.
#}
{% macro aplicar_contrato_iceberg() %}
  {%- if execute -%}
    {%- for nombre, columna in model.columns.items() -%}
      {%- set col = adapter.quote(nombre) -%}
      {%- for r in columna.constraints if r.type == 'not_null' -%}
        {%- do run_query('alter table ' ~ this ~ ' alter column ' ~ col ~ ' set not null') -%}
      {%- endfor -%}
      {%- if columna.description -%}
        {%- set barra, comilla = "\\", "'" -%}
        {%- set texto = columna.description | trim | replace(barra, barra ~ barra) | replace(comilla, barra ~ comilla) -%}
        {%- do run_query('alter table ' ~ this ~ ' alter column ' ~ col ~ ' comment ' ~ comilla ~ texto ~ comilla) -%}
      {%- endif -%}
    {%- endfor -%}
  {%- endif -%}
  select 1
{% endmacro %}
