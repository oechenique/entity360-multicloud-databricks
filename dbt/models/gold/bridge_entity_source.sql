-- De qué registros de qué fuentes sale cada entidad (regla 09).
select
    er.entity_id,
    r.clave as registro,
    r.fuente,
    r.id_fuente,
    r.nombre as nombre_en_fuente,
    r.clave = g.registro_ancla as es_ancla
from {{ source('resolution', 'entidad_registro') }} as er
join {{ source('resolution', 'registro') }} as r on r.clave = er.clave
join {{ source('resolution', 'golden_record') }} as g on g.entity_id = er.entity_id
