# ADR 0009 — Los productores empujan al landing (UC Volume), con manifest por lote

- **Estado:** aceptado (fases 0 y 1, 2026-09-25). Formaliza la decisión de la regla 01 y D2, D3, D6, D9 del
  spike (`spike/INFORME.md`).
- **Relacionado:** ADR 0002 (un SP por productor), ADR 0006 (Bronze exige el contrato).

## Contexto
Cinco fuentes viven en cinco "sistemas" distintos: un SQL Server on-prem, AWS, GCP y un container. Free
Edition usa default storage y la documentación dice que la salida a internet está restringida: Databricks
no puede ir a buscar los datos a cada lugar de forma confiable. Además, cada sistema tiene que poder
fallar o atrasarse sin frenar a los demás.

## Decisión
- **Push:** cada productor escribe primero en su propio almacenamiento (el respaldo de su nube) y después
  empuja el lote al volume `entity360.landing.raw` con la Files API, autenticado con su propio SP
  (OAuth M2M). Se mantiene aunque la salida esté abierta (D9): no depender de algo que la doc dice
  restringido, y cada nube guarda su copia.
- **Contrato común de landing:** `raw/<fuente>/ingest_date=AAAA-MM-DD/<fuente>_<ts>.jsonl` más
  `_manifest_<ts>.json` con fuente, registros, sha256, extracción y versión del productor (D2, D3). El
  manifest se sube **después** del archivo: su llegada es la señal para Airflow y para Bronze.
- **Idempotencia en tres capas (D6):** el productor no empuja si el sha256 no cambió; Bronze descarta
  lotes ya ingeridos; Silver se queda con la última extracción por clave natural.

## Consecuencias
- Agregar una fuente es escribir un productor que cumpla el contrato: el resto de la plataforma no cambia.
- Un productor caído se ve como una fuente atrasada (sensores de Airflow, `dbt source freshness`), no
  como un error del pipeline.
- Cada lote pasa por el contrato de llegada (Soda) antes de Bronze (ADR 0006).
