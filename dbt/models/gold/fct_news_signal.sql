-- Menciones en noticias por entidad y día, con tono (GDELT, regla 09). Un documento que menciona a
-- dos entidades cuenta para las dos.
select
    b.entity_id,
    cast(m.fecha_gdelt as date) as fecha,
    count(*) as menciones,
    count(distinct m.medio) as medios,
    round(avg(m.tono), 3) as tono_promedio,
    min(m.tono) as tono_min,
    max(m.tono) as tono_max,
    cast(sum(case when m.tono < 0 then 1 else 0 end) as bigint) as menciones_negativas
from {{ source('silver', 'gdelt_mencion') }} as m
join {{ ref('bridge_entity_source') }} as b on b.registro = concat('gdelt:', m.entidad)
group by b.entity_id, cast(m.fecha_gdelt as date)
