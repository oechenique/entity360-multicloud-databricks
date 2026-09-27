-- Golden record: una fila por empresa (regla 09). Sale de la resolución de identidades (regla 08).
select
    g.entity_id,
    g.nombre,
    g.pais,
    g.ciudad,
    g.lei,
    g.cik,
    g.ticker,
    g.sitio_web,
    g.forma_juridica,
    g.estado_entidad,
    g.estado_registro,
    g.sancionada,
    g.en_listas_de_riesgo,
    g.fuentes,
    g.registros,
    g.duplicados_en_gleif,
    g.registro_ancla,
    g.procedencia,
    g.corrida_utc as resuelto_utc
from {{ source('resolution', 'golden_record') }} as g
