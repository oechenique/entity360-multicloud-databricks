# ADR 0001 — "account users" como rol de consumo (limitación de Free Edition)

- **Estado:** aceptado (fase 1, 2026-09-25)
- **Contexto de la regla:** 03 ("Grants por rol: productores, ingeniería, consumo (lectura de `gold`)").

## Contexto
Unity Catalog otorga permisos a principales de **cuenta** (usuarios, service principals y grupos
de cuenta). En Databricks Free Edition no hay acceso a la consola de cuenta, así que no se pueden
crear grupos de cuenta propios (por ejemplo, `entity360-consumidores`). Los grupos de workspace no
sirven para grants de Unity Catalog.

## Decisión
El rol de **consumo** se implementa con el grupo de sistema `account users`:
- `USE_CATALOG` sobre `entity360`.
- `USE_SCHEMA` y `SELECT` sobre `entity360.gold`.

El rol de **ingeniería** es el owner del catálogo (el usuario del workspace). El rol de
**productores** es el service principal `entity360-producer`, con grants directos y mínimos
sobre `landing.raw`.

En un workspace pago, consumo sería un **grupo de cuenta** (`entity360-consumidores`) administrado
desde la consola de cuenta o con Terraform a nivel cuenta, y los grants irían a ese grupo.

## Consecuencias
- **Todos los principales de la cuenta leen `gold`, incluido el SP de productores.** Verificado en
  el smoke test de la fase 1 (`tests/smoke_producer_push.py`, paso 5): el SP hereda
  `USE_CATALOG`, `USE_SCHEMA` y `SELECT` sobre `gold` por pertenecer a `account users`.
- **La escritura no se ve afectada:** el SP solo escribe en `landing.raw` (paso 4: crear otro
  volume da 403). La regla 03 ("solo puede escribir en el volume") se cumple.
- Es aceptable porque `gold` es, por definición, la capa publicada para consumo, y en Free Edition
  la cuenta tiene un solo usuario humano.
- `EXTERNAL_USE_SCHEMA` sobre `gold` **no** se da a `account users`: se otorga en la fase 9 solo al
  principal que use Snowflake (regla 11).

## Cómo migrar a un workspace pago
1. Crear el grupo de cuenta `entity360-consumidores` y agregar a los consumidores.
2. Cambiar `principal = "account users"` por el grupo en `infra/databricks/consumption.tf`.
3. `terraform apply`: los `databricks_grant` no son autoritativos, así que hay que revocar a mano
   (o con un apply que los elimine) los grants de `account users`.
