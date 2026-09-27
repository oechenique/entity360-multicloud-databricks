-- Coincidencias de entidades con listas de riesgo (OpenSanctions, regla 09). Una fila por entidad y
-- registro de OpenSanctions que la resolución unió a ella. lei_coincide = el registro de la lista
-- trae el mismo LEI que el golden record (vínculo por identificador, no solo por nombre).
select
    b.entity_id,
    o.id as opensanctions_id,
    o.nombre as nombre_en_lista,
    o.esquema,
    o.sancionada,
    o.sanciones,
    o.datasets,
    o.paises,
    coalesce(array_contains(o.leis, d.lei), false) as lei_coincide,
    o.primera_vez,
    o.ultimo_cambio
from {{ source('silver', 'opensanctions_entidad') }} as o
join {{ ref('bridge_entity_source') }} as b on b.registro = concat('opensanctions:', o.id)
join {{ ref('dim_entity') }} as d on d.entity_id = b.entity_id
