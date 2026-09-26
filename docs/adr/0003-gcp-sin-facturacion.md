# ADR 0003 — GCP sin facturación: GDELT desde GitHub Actions con BigQuery sandbox

- **Estado:** aceptado (fase 4, 2026-09-26). Decisión de Gastón.
- **Reemplaza:** el diseño original de la regla 06 (Cloud Scheduler → Cloud Run Job → BigQuery →
  GCS, credenciales en Secret Manager, cada 15 minutos).
- **Relacionado:** D10 y D12 del spike, ADR 0002 (un SP por productor).

## Contexto
La regla 06 ponía el productor de GDELT en GCP con Cloud Run, Cloud Scheduler, GCS y Secret Manager.
Todos requieren una cuenta de facturación. El proyecto de GCP corre en **modo sandbox**, sin cuenta
de facturación (D10), y el alta del trial pide un prepago que **no se va a pagar**.

Lo que el sandbox sí da, sin cuenta de facturación y sin costo posible: BigQuery (1 TiB de consultas
y 10 GB de almacenamiento por mes), IAM y Workload Identity Federation.

## Decisión
**No se activa facturación en GCP.** GDELT se extrae desde GitHub Actions:

| Pieza original | Reemplazo | Por qué alcanza |
|---|---|---|
| Cloud Scheduler | Cron de GitHub Actions (`gdelt-horario.yml`) | Es el mismo plano de ejecución que el container de enriquecimiento (fase 5) |
| Cloud Run Job | Imagen en GHCR corrida por el workflow | Mismo patrón que la fase 5 |
| Credenciales de SA | **Workload Identity Federation**: el token OIDC de GitHub se cambia por credenciales cortas de la SA `entity360-gdelt` (impersonación) | Sin claves de SA en ningún lado (principio 4). El provider acepta solo este repo, la rama `main` y los workflows `gdelt-*` |
| GCS (respaldo) | Tabla particionada de BigQuery sandbox (`entity360_gdelt`), escrita con **load jobs** | Cada productor respalda en su nube (regla 01) |
| Secret Manager | GitHub Secrets (SP de Databricks `entity360-producer-gdelt`, provider WIF, SA y proyecto) | Secret Manager requiere facturación |
| Alertas de presupuesto (principio 5) | No aplican | Sin cuenta de facturación no hay cargo posible (D10). Los guardarraíles de consumo son el dry run y `maximum_bytes_billed` = 1 GiB por consulta (D12) |

## Verificado (paso 0, 2026-09-26)
- Las APIs `iam`, `iamcredentials`, `sts` y `cloudresourcemanager` se habilitaron sin cuenta de
  facturación, y también se crearon el pool y el provider de WIF, la SA, sus bindings y el dataset.
- Desde GitHub Actions: token OIDC → SA por impersonación → dry run de GKG con filtro de partición
  (15,9 MB para el día en curso). El ID del proyecto no aparece en el log.
- BigQuery sandbox: los **load jobs** y las consultas con tabla de destino (`WRITE_APPEND`)
  funcionan. **DML (`INSERT`/`MERGE`) no**: `403 ... DML queries are not allowed in the free tier`.
- **Expiración:** el sandbox impone 60 días por defecto a tablas y particiones del dataset (quedan
  declarados en Terraform para evitar drift). Una tabla **particionada** creada por load job queda
  sin expiración de tabla: solo vencen sus particiones. El respaldo es una ventana móvil de 60 días.

## Consecuencias
- **Cadencia horaria, no cada 15 minutos.** GDELT publica cada 15 minutos, pero una corrida cada 15
  minutos son ~2.900 jobs por mes y cada job se factura como 1 minuto mínimo, por encima de los 2.000
  minutos gratis del repo privado. "Casi tiempo real" pasa a ser "horario" y el README lo dice así.
- **Minutos de Actions** (repo privado, 2.000/mes; cada job se redondea hacia arriba al minuto):

  | Workflow | Jobs por mes | Minutos |
  |---|---|---|
  | `gdelt-horario` (< 60 s por corrida) | 720–744 | 720–744 |
  | `enriquecimiento-diario` (34 s medidos) | 30–31 | 30–31 |
  | Builds de imágenes (~30 s) | ~10 | ~10 |
  | **Total** | | **~785 (39 %)** |

  Si GDELT pasa de 60 s por corrida, cada job cuesta 2 minutos (~1.530, 77 %) y se baja a **cada 2
  horas** (~370). Sin medio de pago cargado, pasarse del cupo bloquea los workflows, no cobra.
- **Cuota de BigQuery:** cada corrida escanea las columnas de la partición del día hasta ese momento
  (0,05–0,2 GiB). Son ~40–140 GiB por mes contra 1 TiB gratis. Pasarse falla, no cobra.
- **Sin DML:** la idempotencia por `GKGRECORDID` se resuelve en la consulta (excluye los ids que ya
  están en el respaldo) y el respaldo se escribe con load jobs.
- **Respaldo de 60 días:** alcanza para la deduplicación (mira las últimas horas) y para reintentar
  un push. El histórico largo vive en Bronze/Silver de Databricks, no en GCP.
- **El cron de Actions no es exacto:** en horas de carga se atrasa o saltea corridas. La ventana de
  la consulta cubre más de una hora para que un salteo no pierda menciones.

## Cómo migrar a GCP con facturación
Con una cuenta de facturación: presupuesto con alertas **primero** (principio 5); después Cloud Run Job
con la misma imagen, Cloud Scheduler cada 15 minutos, la misma SA (sin WIF: identidad nativa de Cloud
Run), respaldo en GCS o en la misma tabla y el secreto del SP en Secret Manager. La consulta, el
diccionario de alias y el push no cambian.
