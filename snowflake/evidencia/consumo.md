# Consumo de Snowflake (fase 9, trial Enterprise en AWS us-east-2, alta 2026-09-29)

Estimación del plan: ~13–15 créditos por mes (`docs/fase9-plan.md` §6). Acá va lo medido.

## Qué frena cada tope
| Tope | Qué cubre | Qué NO cubre |
|---|---|---|
| `ENTITY360_MONITOR` (20 créditos/mes, nivel warehouse) | `ENTITY360_WH` (dbt de los marts, modelers) | todo lo demás |
| `ENTITY360_CUENTA` (25 créditos/mes, nivel cuenta) | todos los warehouses de la cuenta: `COMPUTE_WH` (Snowsight), `SNOWFLAKE_LEARNING_WH` y los que aparezcan | cómputo serverless y cloud services |
| **Nada** (solo se mide) | — | **la sincronización de la base catalog-linked** (`ENTITY360_UC`, cada 300 s), tareas serverless, Snowpipe, clustering automático, cloud services por encima del 10 % diario |

Los resource monitors solo controlan warehouses; la documentación de Snowflake recomienda un *budget*
para lo serverless. Por eso lo serverless se mide a mano, a diario, mientras dure el trial.

## Medición diaria
`SNOWFLAKE.ACCOUNT_USAGE` tiene **latencia de horas** (hasta ~3 h según la documentación de cada vista):
lo de hoy se ve recién mañana; se anota el día anterior. Se corre con `ENTITY360_TF` o con un usuario de
ACCOUNTADMIN, una sentencia por línea:

```sql
SELECT usage_date, service_type, ROUND(SUM(credits_used), 4) AS creditos, ROUND(SUM(credits_billed), 4) AS facturados FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY WHERE usage_date >= '2026-09-29' GROUP BY 1, 2 ORDER BY 1, 2;
SELECT DATE_TRUNC('day', start_time) AS dia, service_type, name, ROUND(SUM(credits_used), 4) AS creditos FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE start_time >= '2026-09-29' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
SELECT DATE_TRUNC('day', start_time) AS dia, warehouse_name, ROUND(SUM(credits_used), 4) AS creditos FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE start_time >= '2026-09-29' GROUP BY 1, 2 ORDER BY 1, 2;
SHOW RESOURCE MONITORS LIKE 'ENTITY360%';
```

- `METERING_DAILY_HISTORY`: créditos por día y tipo de servicio, incluido el ajuste de cloud services
  (`credits_billed`).
- `METERING_HISTORY`: por hora, servicio y objeto; ahí aparece la sincronización catalog-linked con su
  `service_type` (a identificar en la primera medición).
- `WAREHOUSE_METERING_HISTORY`: lo que ven los monitores.
- `SHOW RESOURCE MONITORS`: `used_credits` sin latencia, solo de warehouses.

## Registro
| Día (UTC) | Warehouses | Serverless (catalog-linked y otros) | Cloud services facturados | Total | Acumulado | Nota |
|---|---|---|---|---|---|---|
| 2026-09-29 | | | | | | alta del trial, Terraform, integración (a medir el 2026-09-30) |
