# ADR 0001 — Sin grants de consumo a "account users": consumo por principal dedicado

- **Estado:** aceptado (fase 1, 2026-09-25). Reemplaza la primera versión de este ADR, que usaba
  `account users` como rol de consumo.
- **Contexto de la regla:** 03 ("Grants por rol: productores, ingeniería, consumo (lectura de `gold`)").

## Contexto
Unity Catalog otorga permisos a principales de **cuenta** (usuarios, service principals y grupos
de cuenta). En Databricks Free Edition no hay acceso a la consola de cuenta, así que no se pueden
crear grupos de cuenta propios (por ejemplo, `entity360-consumidores`), y los grupos de workspace
no sirven para grants de Unity Catalog.

La primera versión de la fase 1 usó el grupo de sistema `account users` como rol de consumo
(`USE_CATALOG` + `USE_SCHEMA`/`SELECT` sobre `gold`). El smoke test mostró el costo: **todos los
principales de la cuenta son miembros de `account users`, incluido el SP de productores**, que
heredaba la lectura de `gold`. Eso rompe el mínimo privilegio del SP.

## Decisión
- **No hay grants de consumo a `account users`.** Se eliminaron (`infra/databricks/consumption.tf`
  ya no existe).
- **Ingeniería** es el owner del catálogo (el usuario del workspace): no necesita grants.
- **Productores:** el SP `entity360-producer` con grants directos y mínimos sobre `landing.raw`
  (`USE_CATALOG`, `USE_SCHEMA` en `landing`, `READ_VOLUME`/`WRITE_VOLUME` en `raw`).
- **Consumo:** se otorga a un **principal dedicado cuando exista**. El primero es el de Snowflake
  en la fase 9 (regla 11): `USE_CATALOG`, `USE_SCHEMA` y `SELECT` sobre `gold`, más
  `EXTERNAL_USE_SCHEMA` sobre `gold` para el Camino A. El dashboard y Genie corren con el usuario
  owner.

En un workspace pago, el consumo sería un **grupo de cuenta** (`entity360-consumidores`) con
esos mismos grants sobre `gold`, y los principales de consumo se agregarían al grupo.

## Consecuencias
- El SP de productores **no puede leer `gold`** ni escribir fuera del volume. Verificado en
  `tests/smoke_producer_push.py`: crear otro volume da 403 (paso 4) y leer el schema `gold` da 403
  (paso 5).
- Hasta la fase 9 nadie más que el owner lee `gold`. Es coherente con Free Edition (un solo
  usuario humano).
- Cada consumidor nuevo implica un grant explícito en Terraform: más líneas, pero cada acceso
  queda visible y justificado.

## Cómo migrar a un workspace pago
1. Crear el grupo de cuenta `entity360-consumidores`.
2. Agregar en `infra/databricks/` los `databricks_grant` de consumo sobre `gold` para ese grupo.
3. Sumar al grupo los principales de consumo (incluido el de Snowflake).
