# 09 — Fase 7: Contratos de datos y Gold (Data Contract Enforcer)

Esta fase absorbe el proyecto "Data Contract Enforcer" que había quedado pendiente.

## Contratos en la llegada (Soda Core)
- Un archivo de checks por fuente en `contracts/`: esquema esperado, no nulos, unicidad,
  valores válidos, frescura, volumen dentro de un rango razonable.
- Corre en Airflow antes de procesar cada lote.
- Si falla un check crítico: el lote va a cuarentena y se genera una alerta. El resto de
  las fuentes sigue su camino: un proveedor roto no frena la plataforma.

## Contratos en los modelos (dbt)
- dbt Core con targets `databricks` y `snowflake` (este último en la fase 9).
- Modelos Gold:
  - `dim_entity`: golden record, una fila por empresa.
  - `bridge_entity_source`: de qué registros de qué fuentes sale cada entidad.
  - `fct_news_signal`: menciones en noticias por entidad y día, con tono.
  - `fct_risk_flags`: coincidencias con listas de riesgo.
  - `fct_entity_changes`: historial de cambios que vinieron del legacy por CDC.
- `contract: enforced: true` en todos los modelos Gold.
- Tests de unicidad, no nulos, relaciones y rangos; tests de frescura por fuente.
- Documentación y lineage con `dbt docs`, con enlace desde el README.

## Alertas
- Canal simple y verificable (mail o Telegram) para fallos críticos de contratos y fuentes
  atrasadas.
