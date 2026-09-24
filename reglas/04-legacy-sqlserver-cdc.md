# 04 — Fase 2: Sistema legacy on-prem (SQL Server + CDC)

**Historia:** el ERP viejo de la organización. Vive "on-premise": un container en la PC.

- `legacy/docker-compose.yml` con SQL Server (edición Developer, Agent habilitado).
  Contraseña en `.env` local, fuera de git.
- Modelo transaccional normalizado (entidades, direcciones, relaciones), no un volcado
  plano: tiene que parecer una base operativa real.
- Carga inicial desde GLEIF para el universo acotado.
- Actualizaciones: un proceso que aplica al SQL Server las novedades diarias de GLEIF
  (altas, cambios de nombre, bajas). Así los cambios que capta el CDC son reales.
- CDC habilitado en las tablas relevantes.
- **Extractor de CDC** (`producers/cdc_extractor`): lee los cambios desde el último LSN
  procesado, los escribe como archivos al volume con el contrato de landing, y guarda el
  checkpoint del LSN. Idempotente.
- Mejora opcional documentada: Debezium Server para publicar los cambios como eventos.

Verificación: cambiar un registro en SQL Server y ver el cambio llegar al volume y a
Bronze, con su operación (insert/update/delete).

**Limitación asumida:** corre cuando la PC está prendida. Es coherente con la historia
(on-prem) y se documenta.
