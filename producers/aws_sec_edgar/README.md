# Productor AWS: SEC EDGAR

Regla 05. Otro "sistema" de la organización: la extracción programada de presentaciones ante la
SEC, con respaldo en S3 propio, que empuja al landing de Databricks.

```text
EventBridge Scheduler (08:00 BA) -> Lambda extractor -> S3 lotes/ + estado/
                                                           | (ObjectCreated _manifest_*.json)
                                                           v
                                     Lambda entrega -> OAuth M2M (SP entity360-producer-sec-edgar)
                                                           -> /Volumes/entity360/landing/raw/sec_edgar/
Fallos (2 reintentos) -> DLQ SQS -> alarma CloudWatch (> 0 mensajes) -> SNS -> mail
```
Infra: `infra/aws/sec_edgar/` (us-east-1, state propio).

## Piezas
| Archivo | Qué hace |
|---|---|
| `universo.json` | Los 16 emisores AR con CIK (spike B.9) |
| `extractor.py` | Baja `submissions/CIK##########.json` con el User-Agent de la SEC y ≤5 req/s; arma un lote solo con los emisores que tienen una presentación nueva; escribe datos, manifest y estado, en ese orden |
| `entrega.py` | Disparada por el manifest: verifica el sha256, pide token OAuth M2M con el secreto de Secrets Manager y sube datos y manifest al volume |
| `credenciales.py` | Crea un secreto del SP del productor (90 días) y lo carga en Secrets Manager; valida AWS antes de crear el secreto |

## Idempotencia
- **Extractor:** CIK + número de accesión de la última presentación (más preciso que la fecha:
  un emisor puede presentar varias cosas el mismo día). Estado en `estado/ultimas.json`. Sin
  presentaciones nuevas, no escribe lote.
- **Entrega:** si el archivo ya está en el volume (reintento), compara el sha256; si coincide sigue,
  si no falla (y el evento termina en la DLQ).
- Si el extractor se corta entre el manifest y el estado, la corrida siguiente re-emite los mismos
  emisores con otro `extraido_utc` (otro sha256): lo deduplica Silver por (CIK, accesión) (D6,
  capa 3).

## Verificación de punta a punta (2026-09-25)
1. Invocación del extractor: 16 emisores con presentación nueva (primera corrida), lote de 2,2 MB.
2. La entrega se disparó sola por la notificación de S3 y subió datos y manifest en 2 s.
3. `read_files` sobre `/Volumes/entity360/landing/raw/sec_edgar/`: 16 filas con nombre, fecha y
   formulario de la última presentación.
4. Segunda invocación: 0 con presentación nueva, sin lote nuevo.
5. DLQ vacía; alarma en `OK`.
