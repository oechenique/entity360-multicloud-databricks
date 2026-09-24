# 05 — Fase 3: Productor AWS (SEC EDGAR)

- AWS Budget con alertas ya creado (verificar antes de empezar).
- Región `us-east-1`, perfil `tesseract`.
- EventBridge Scheduler dispara una Lambda (Python) una vez por día.
- La Lambda baja el JSON de submissions de las empresas del universo (con el `User-Agent`
  exigido y respetando el límite de requests), y escribe crudo en un bucket S3 propio.
- Una notificación de S3 dispara una segunda Lambda que empuja el archivo al volume.
  Separar extracción y entrega hace que cada una se pueda reintentar sola.
- Credenciales de Databricks en Secrets Manager. Fallos a una DLQ (SQS).
- Idempotencia por CIK + fecha de la última presentación.
- Terraform en `infra/aws/`.
