{#
  Gold es del SP entity360-orquestador (ADR 0007): dbt en Airflow recrea las tablas con CREATE OR REPLACE y
  necesita ser el dueño. Si otro principal corre dbt (por ejemplo, el usuario desde la PC), la tabla
  queda a su nombre y la próxima corrida del DAG falla con PERMISSION_DENIED (pasó el 2026-09-29).

  - pre-hook `exigir_duenio_gold()`: corta antes de crear nada si falta E360_GOLD_OWNER.
  - post-hook `asignar_duenio_gold()`: al final de cada modelo, ALTER TABLE ... OWNER TO el SP. Si ya es
    el dueño, no cambia nada.

  E360_GOLD_OWNER es el application_id del SP: en Airflow lo pone docker-compose.yml; en la PC,
  `terraform -chdir=infra/databricks output -raw orquestador_sp_application_id` (dbt/README.md).
#}
{% macro exigir_duenio_gold() %}
  {%- if execute and not env_var('E360_GOLD_OWNER', '') -%}
    {{ exceptions.raise_compiler_error(
        "Falta E360_GOLD_OWNER (application_id del SP entity360-orquestador): Gold tiene que quedar a su "
        ~ "nombre (ADR 0007). Ver dbt/README.md.") }}
  {%- endif -%}
  select 1
{% endmacro %}

{% macro asignar_duenio_gold() %}
  {%- if execute -%}
    {%- do run_query('alter table ' ~ this ~ ' owner to `' ~ env_var('E360_GOLD_OWNER') ~ '`') -%}
  {%- endif -%}
  select 1
{% endmacro %}
