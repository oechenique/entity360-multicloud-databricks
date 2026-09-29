{#
  on-run-end (fase 10, regla 12): una fila por nodo en ops.dbt_resultado (tabla de Terraform,
  infra/databricks/consumo.tf), para el panel de salud del dashboard. Cubre `dbt build`, `run`, `test` y
  `source freshness`, a mano o desde Airflow (Cosmos corre una invocación por modelo: cada una suma sus
  filas). Si la tabla no existe, avisa y no falla: registrar resultados no puede tumbar una corrida.
#}
{% macro registrar_resultados(results) %}
  {#- Solo Databricks: ops.dbt_resultado vive en Unity Catalog. -#}
  {%- if execute and results and target.type == 'databricks' -%}
    {%- set tabla = adapter.get_relation(database=target.catalog, schema='ops', identifier='dbt_resultado') -%}
    {%- if tabla is none -%}
      {{ log("ops.dbt_resultado no existe: no se registran los resultados", info=true) }}
    {%- else -%}
      {%- set barra, comilla = "\\", "'" -%}
      {%- set filas = [] -%}
      {%- for r in results -%}
        {%- set mensaje = (r.message or '') | string | truncate(1000, true, '') | replace(barra, barra ~ barra) | replace(comilla, barra ~ comilla) -%}
        {%- do filas.append("('" ~ invocation_id ~ "', '" ~ flags.WHICH ~ "', '" ~ r.node.unique_id ~ "', '"
            ~ r.node.resource_type ~ "', '" ~ r.status ~ "', " ~ (r.failures if r.failures is not none else 'null')
            ~ ", '" ~ mensaje ~ "', " ~ (r.execution_time or 0) ~ ", current_timestamp())") -%}
      {%- endfor -%}
      {%- do run_query('insert into ' ~ tabla ~ ' values ' ~ filas | join(', ')) -%}
    {%- endif -%}
  {%- endif -%}
  select 1
{% endmacro %}
