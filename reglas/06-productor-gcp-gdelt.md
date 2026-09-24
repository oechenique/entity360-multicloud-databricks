# 06 — Fase 4: Productor GCP (GDELT, casi tiempo real)

- Budget con alertas en el proyecto de GCP antes de crear nada.
- Cloud Scheduler dispara cada 15 minutos un Cloud Run Job (Python).
- El job consulta en BigQuery las menciones nuevas de organizaciones del universo, **con
  filtro de partición obligatorio** y un límite de bytes facturables en la query
  (`maximum_bytes_billed`), para que un error nunca escanee de más.
- Escribe el resultado en GCS y lo empuja al volume.
- Service account dedicada con permisos mínimos. Credenciales de Databricks en Secret
  Manager.
- Idempotencia por identificador de evento de GDELT.
- Terraform en `infra/gcp/`.

Nota de honestidad para el README: es micro-batch cada 15 minutos, "casi tiempo real".
