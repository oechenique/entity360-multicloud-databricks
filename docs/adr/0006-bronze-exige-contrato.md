# ADR 0006 — Bronze exige el veredicto del contrato de llegada; el job lo dispara Airflow

- **Estado:** aceptado (fase 7, 2026-09-27). Decisión de Gastón.
- **Relacionado:** regla 09 (contratos en la llegada, "antes de procesar cada lote"), regla 10
  (Airflow como plano de control), ADR 0004 (job de PySpark), D6 (idempotencia en tres capas).

## Contexto
Los contratos de llegada (`contracts/verificar.py`, Soda Core) escriben un veredicto
`_contrato_<ts>.json` por lote, y Bronze no ingiere un lote en `cuarentena`. Pero hasta ahora Bronze
**sí ingería un lote sin veredicto**: el job corría solo a las 08:45 (schedule de Databricks) y los
contratos van a correr en Airflow, que es local. Si Airflow no corría antes (PC apagada, DAG
atrasado), un lote malo entraba a Bronze sin verificar, y Auto Loader ya no lo vuelve a entregar.

## Decisión
1. **Bronze exige el veredicto, igual que exige el manifest.** Un lote sin `_contrato_<ts>.json`, o con
   un veredicto de otro sha256 (el archivo cambió después de verificarse), hace fallar el micro-batch
   de su fuente con `ContratoPendiente`: el checkpoint no avanza y el lote se vuelve a tomar en la
   corrida siguiente (`databricks/medallion/capa2.py`).
2. **El schedule de las 08:45 del job queda pausado** (`pause_status = "PAUSED"` en
   `infra/databricks/medallion.tf`). El job lo dispara Airflow (fase 8), después de correr los contratos
   sobre los lotes pendientes.

## Consecuencias
- **Ningún lote entra a Bronze sin verificar.** La cuarentena deja de depender del orden en que
  corrieron las cosas.
- **Con la PC apagada no se procesa nada nuevo** (Airflow es local, regla 10). No se pierde nada:
  los productores siguen aterrizando en el volume y el primer ciclo de Airflow procesa lo acumulado.
  Es la misma limitación que ya tenía el CDC del legacy (regla 04), y se documenta en el README.
- Si se dispara el job a mano sin haber corrido los contratos, Bronze falla con un mensaje que dice
  qué lotes faltan verificar y cómo (`contracts/verificar.py --pendientes`).
- Un veredicto de otro contenido no se re-verifica solo (los productores nunca reescriben un archivo:
  cada lote tiene su timestamp). Si pasa, se borra ese `_contrato` y se vuelve a verificar.

## Cómo volver atrás
Reactivar el schedule (`UNPAUSED`) y, en `capa2.clasificar`, tratar el lote sin veredicto como
`aprobado`. La cuarentena de los lotes verificados sigue funcionando igual.
