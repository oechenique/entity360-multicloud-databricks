-- Señal de noticias por empresa y día, con la media móvil de 7 días para detectar picos (marketing y
-- riesgo). Datos: The GDELT Project (https://www.gdeltproject.org/).
select
    n."entity_id" as entity_id,
    d."nombre" as nombre,
    d."pais" as pais,
    n."fecha" as fecha,
    n."menciones" as menciones,
    n."medios" as medios,
    n."menciones_negativas" as menciones_negativas,
    n."tono_promedio" as tono_promedio,
    avg(n."menciones") over (
        partition by n."entity_id" order by n."fecha" rows between 6 preceding and current row
    ) as menciones_media_7d
from {{ source('gold_uc', 'fct_news_signal') }} as n
join {{ source('gold_uc', 'dim_entity') }} as d on d."entity_id" = n."entity_id"
