-- Empresas en listas de riesgo, una fila por aparición, con el contexto que pide un analista de riesgo:
-- identidad, qué lista, cómo se vinculó y la cobertura reciente. Datos: OpenSanctions
-- (opensanctions.org), CC BY-NC 4.0.
select
    r."entity_id" as entity_id,
    d."nombre" as nombre,
    d."pais" as pais,
    d."lei" as lei,
    r."opensanctions_id" as opensanctions_id,
    r."nombre_en_lista" as nombre_en_lista,
    r."esquema" as esquema,
    r."sancionada" as sancionada,
    r."sanciones" as sanciones,
    -- Iceberg trae un ARRAY estructurado (ARRAY(VARCHAR)); ARRAY_TO_STRING pide el semiestructurado.
    array_to_string(r."datasets"::array, ', ') as listas,
    iff(r."lei_coincide", 'LEI', 'nombre') as vinculo,
    r."primera_vez" as primera_vez,
    r."ultimo_cambio" as ultimo_cambio,
    m.menciones_30d,
    m.tono_30d
from {{ source('gold_uc', 'fct_risk_flags') }} as r
join {{ source('gold_uc', 'dim_entity') }} as d on d."entity_id" = r."entity_id"
left join {{ ref('mart_empresa') }} as m on m.entity_id = r."entity_id"
