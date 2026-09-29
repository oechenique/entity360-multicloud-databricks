-- Una fila por empresa con todo lo que un modeler suele cruzar: identidad, fuentes, noticias de los
-- últimos 30 días, riesgo y cambios recientes del legacy. Snowflake, sobre Gold (fase 9).
with noticias as (
    select
        "entity_id" as entity_id,
        sum("menciones") as menciones_30d,
        sum("menciones_negativas") as menciones_negativas_30d,
        sum("tono_promedio" * "menciones") / nullif(sum("menciones"), 0) as tono_30d
    from {{ source('gold_uc', 'fct_news_signal') }}
    where "fecha" >= dateadd(day, -30, current_date())
    group by 1
),

riesgo as (
    select
        "entity_id" as entity_id,
        count(*) as listas_de_riesgo,
        count_if("sancionada") as listas_con_sancion,
        boolor_agg("lei_coincide") as vinculo_por_lei
    from {{ source('gold_uc', 'fct_risk_flags') }}
    group by 1
),

cambios as (
    select
        "entity_id" as entity_id,
        count(*) as cambios_legacy_90d
    from {{ source('gold_uc', 'fct_entity_changes') }}
    where "operacion" <> 'insert' and "valido_desde" >= dateadd(day, -90, current_timestamp())
    group by 1
)

select
    d."entity_id" as entity_id,
    d."nombre" as nombre,
    d."pais" as pais,
    d."ciudad" as ciudad,
    d."lei" as lei,
    d."cik" as cik,
    d."ticker" as ticker,
    d."forma_juridica" as forma_juridica,
    d."estado_entidad" as estado_entidad,
    d."registros" as registros,
    array_size(d."fuentes") as fuentes,
    d."duplicados_en_gleif" as duplicados_en_gleif,
    coalesce(n.menciones_30d, 0) as menciones_30d,
    coalesce(n.menciones_negativas_30d, 0) as menciones_negativas_30d,
    round(n.tono_30d, 3) as tono_30d,
    d."sancionada" as sancionada,
    coalesce(r.listas_de_riesgo, 0) as listas_de_riesgo,
    coalesce(r.listas_con_sancion, 0) as listas_con_sancion,
    coalesce(r.vinculo_por_lei, false) as riesgo_vinculado_por_lei,
    coalesce(c.cambios_legacy_90d, 0) as cambios_legacy_90d,
    d."resuelto_utc" as resuelto_utc
from {{ source('gold_uc', 'dim_entity') }} as d
left join noticias as n on n.entity_id = d."entity_id"
left join riesgo as r on r.entity_id = d."entity_id"
left join cambios as c on c.entity_id = d."entity_id"
