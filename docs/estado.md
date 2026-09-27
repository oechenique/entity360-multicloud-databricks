# Estado del proyecto

Última actualización: **2026-09-27, 22:00 UTC**. Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fase 7 (regla 09) cerrada. Sigue la fase 8 (Airflow), con una decisión pendiente (abajo).**

## Hecho
- **Fases 0 a 5** cerradas (spike, base de Databricks, legacy con CDC, SEC EDGAR, GDELT, enriquecimiento).
  - GDELT: el cron de Actions saltea horas (3 corridas en 20 h el 2026-09-27); la ventana pasó a
    24 h para no perder menciones (ADR 0003).
- **Fase 6 (regla 08):**
  - Job `entity360-medallion`: bronze → silver → resolucion, schedule diario 08:45 (Buenos Aires).
    Consumo: 0,6–1,2 DBU por corrida (`databricks/evidencia/pasos1-3-primeras-corridas.txt`).
  - Resolución de identidades (`databricks/medallion/identidades.py`, pesos **sin calibrar**): 1268
    registros → 1132 entidades; 17 casos a revisar y 16 conflictos en `resolution.revision`.
  - Set de validación: **parte A etiquetada** (59 registros) y **parte B generada** (60 pares, sin
    etiquetar), en `databricks/resolucion/validacion/`.
- **Fase 7 (regla 09):**
  - Contratos de llegada con Soda Core 4 (`contracts/`): 5 fuentes, veredicto `_contrato_<ts>.json`
    por lote, cuarentena en Bronze (`cuarentena_contrato`) y alerta por Telegram. Los 10 lotes del
    landing, aprobados.
  - dbt (`dbt/`): 5 modelos Gold en Iceberg gestionado con contratos enforced (ADR 0005); `dbt build`
    24/24 y `dbt source freshness` 7/7.
- Tests: 97 en `tests/medallion`, 38 en `tests/gcp_gdelt`, 19 en `tests/contracts` (entorno
  `contracts\.venv`).

## Pendiente
1. **Etiquetar la parte B (Gastón):** `databricks/resolucion/validacion/parte_b.csv`, instrucciones en
   el README de esa carpeta (`respuesta` `si`/`no`/`incierto`, `evidencia`, `fecha`). No abrir
   `parte_b_estratos.csv` antes de terminar.
2. **Paso 5 de la fase 6, después de la parte B:** calibrar pesos y umbrales con la mitad del set
   (partición por estrato, semilla fija) y publicar precisión y recall con intervalo de Wilson sobre la
   otra mitad.
3. **Decisión de diseño para la fase 8 — lotes sin veredicto de contrato.** Hoy Bronze ingiere un lote
   que todavía no tiene `_contrato_*.json` (solo frena los que están en cuarentena). Como el job corre
   solo a las 08:45 y los contratos corren en Airflow local, un lote malo puede entrar si Airflow no
   corrió antes. Opciones: (a) Bronze exige el veredicto (como exige el manifest) y el schedule del job
   pasa a Airflow; con la PC apagada no se procesa nada nuevo, pero no se pierde nada. (b) Dejarlo como
   está. Recomendación: (a).
4. **Borrar `entity360.gold.prueba_contrato`:** tabla de prueba de la fase 7 (Iceberg + contrato). Es
   un `DROP TABLE`: espera confirmación.
5. **Canal de alertas:** crear el bot de Telegram (`docs/manual-steps.md` §10). Sin él, las alertas van
   a stderr.

## Estado del entorno al cerrar
- `main` = `origin/main`.
- SQL Server del legacy: contenedor detenido, volumen intacto
  (`docker compose -f legacy\docker-compose.yml start`).
- Sin procesos corriendo. Próxima corrida del job: schedule de las 08:45.
- Entornos locales: `.venv` (fase 6), `contracts\.venv` (Soda), `dbt\.venv` (dbt), todos ignorados.
