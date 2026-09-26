# Extractor CDC (SQL Server legacy → UC Volume)

Regla 04. Lee los cambios del CDC del ERP (`legacy/`) desde el último LSN procesado y los empuja al
volume con el contrato de landing (regla 01), autenticado como el SP `entity360-producer` (recurso `producer_cdc`, ADR 0002) con OAuth M2M.

## Salida
`/Volumes/entity360/landing/raw/sqlserver_cdc/ingest_date=YYYY-MM-DD/`
- `sqlserver_cdc_<ts>.jsonl`: un cambio por línea: `tabla`, `op` (`insert` / `update` / `delete`),
  `lsn`, `seqval`, `commit_time`, `datos` (la fila después del cambio; en `delete`, la fila borrada).
- `_manifest_<ts>.json`: `registros`, `sha256`, `lsn_desde`, `lsn_hasta`, `por_tabla`,
  `por_operacion`, `producer_version`. Se sube **después** del archivo de datos.

## Credenciales (Administrador de credenciales de Windows)
Nada en `.env` ni en disco. `credenciales.py configurar`:
1. Crea un secreto OAuth para el SP (90 días por defecto) con el perfil de Databricks del usuario.
2. Crea (o rota) el login de SQL Server `cdc_extractor`, **solo lectura** (`SELECT` en los schemas
   `cdc` y `erp`): el extractor no usa `sa`.
3. Guarda host, client_id, secreto y contraseña con `keyring` (servicio `entity360-cdc-extractor`).

```powershell
.venv\Scripts\python.exe producers\cdc_extractor\credenciales.py configurar --dias 90
.venv\Scripts\python.exe producers\cdc_extractor\credenciales.py verificar
```
**Rotación:** correr `configurar` de nuevo antes del vencimiento (el primero vence el
2026-12-24). Los secretos viejos del SP vencen solos.

## Checkpoint e idempotencia
- Checkpoint en `state/checkpoint.json` (fuera de git), escrito **después** de subir datos y
  manifest.
- Si el archivo se pierde, se recupera del `lsn_hasta` del último manifest del volume (verificado:
  sin re-emitir nada y restaurando el archivo local).
- Si el cleanup del CDC (3 días por defecto) ya borró cambios posteriores al checkpoint, el
  extractor corta con error: hace falta una recarga, no se inventa continuidad.
- Sin cambios nuevos no empuja nada (D6, capa 1). Si se corta entre el push y el checkpoint, la
  corrida siguiente re-emite el mismo rango y Bronze lo descarta por `sha256` (capa 2).

## Uso
```powershell
.venv\Scripts\python.exe producers\cdc_extractor\extractor.py --solo-leer   # resume, no empuja
.venv\Scripts\python.exe producers\cdc_extractor\extractor.py
```
Corre cuando la PC está prendida (limitación asumida del on-prem, ver `legacy/README.md`).
Airflow lo va a programar en la fase 8.
