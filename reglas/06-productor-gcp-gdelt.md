# 06 — Fase 4: Productor GCP (GDELT, horario)

**Sin facturación en GCP (ADR 0003).** El proyecto corre en modo sandbox; no se crea nada que
requiera cuenta de facturación. Si algún paso la pide, se frena.

- GitHub Actions (`gdelt-horario.yml`) corre una vez por hora una imagen publicada en GHCR.
- Auth a GCP con **Workload Identity Federation**: el token OIDC de GitHub se cambia por credenciales
  cortas de una service account dedicada (`entity360-gdelt`) por impersonación. Sin claves de SA.
  El provider acepta solo este repo, la rama `main` y los workflows `gdelt-*`.
- La SA tiene lo mínimo: `bigquery.jobUser` en el proyecto y `bigquery.dataEditor` solo en el
  dataset de respaldo. GDELT es público: leerlo no necesita permisos.
- La consulta a GKG en BigQuery sandbox lleva **filtro de partición obligatorio**, dry run antes y
  `maximum_bytes_billed` de 1 GiB (D12), para que un error nunca escanee de más.
- Match por un **diccionario de alias traducidos por entidad**, versionado y con evidencia: GDELT
  traduce los nombres palabra por palabra ("bank galicia"). Forma completa, nunca nombres cortos
  ambiguos ("galicia", "macro", "pampa").
- Respaldo del lado de GCP en una tabla particionada de BigQuery sandbox, escrita con load jobs (el
  sandbox no admite DML). Las particiones vencen a los 60 días.
- Después, push al volume con su propio SP (`entity360-producer-gdelt`, ADR 0002). Credenciales de
  Databricks y datos del proyecto en GitHub Secrets; nada identificatorio en los logs.
- Idempotencia por identificador de GDELT (`GKGRECORDID`): la consulta excluye lo que ya está en el
  respaldo, y el push manda solo lo posterior al último manifest.
- Terraform en `infra/gcp/`.
- Minutos de Actions controlados: cada corrida por debajo de 60 s. Si no alcanza, cada 2 horas.

Nota de honestidad para el README: es micro-batch **horario** (GDELT publica cada 15 minutos; la
cadencia la limita el cupo de Actions del repo privado).
