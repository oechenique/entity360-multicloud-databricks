-- Historial de cambios que vinieron del legacy por CDC (regla 09): una fila por versión de cada fila
-- del ERP (SCD tipo 2 de Silver). detalle = los atributos de la versión, como JSON.
-- entity_id es nulo si el LEI ya no está en el legacy (se dio de baja): la historia se conserva.
with cambios as (
    select 'entidad' as tabla_legacy, lei, _clave, _op, _lsn, _seqval, valido_desde, valido_hasta,
           to_json(named_struct('nombre_legal', nombre_legal, 'jurisdiccion', jurisdiccion,
                                'estado_entidad', estado_entidad, 'estado_registro', estado_registro)) as detalle
    from {{ source('silver', 'gleif_entidad_hist') }}
    union all
    select 'direccion', lei, _clave, _op, _lsn, _seqval, valido_desde, valido_hasta,
           to_json(named_struct('tipo', tipo, 'linea1', linea1, 'ciudad', ciudad, 'region', region,
                                'pais', pais, 'codigo_postal', codigo_postal))
    from {{ source('silver', 'gleif_direccion_hist') }}
    union all
    select 'nombre_alternativo', lei, _clave, _op, _lsn, _seqval, valido_desde, valido_hasta,
           to_json(named_struct('orden', orden, 'nombre', nombre, 'tipo', tipo, 'idioma', idioma))
    from {{ source('silver', 'gleif_nombre_alternativo_hist') }}
    union all
    select 'relacion', lei_hijo, _clave, _op, _lsn, _seqval, valido_desde, valido_hasta,
           to_json(named_struct('lei_padre', lei_padre, 'tipo', tipo, 'estado_relacion', estado_relacion,
                                'estado_registro', estado_registro))
    from {{ source('silver', 'gleif_relacion_hist') }}
)
select
    b.entity_id,
    c.lei,
    c.tabla_legacy,
    c._clave as clave_fila,
    c._op as operacion,
    c._lsn as lsn,
    c._seqval as seqval,
    c.valido_desde,
    c.valido_hasta,
    c.valido_hasta is null as vigente,
    c.detalle
from cambios as c
left join {{ ref('bridge_entity_source') }} as b on b.registro = concat('gleif:', c.lei)
