# ADR 0002 — Un service principal por productor

- **Estado:** aceptado (fase 3, 2026-09-25).
- **Reemplaza:** el diseño de la fase 1, con un único SP (`entity360-producer`) para todos los
  productores.

## Contexto
En la fase 3, al crear el secreto OAuth para la Lambda de entrega de SEC EDGAR, Databricks
respondió `RESOURCE_EXHAUSTED: Cannot have more than 5 oauth secrets in one service principal`.
El SP compartido ya tenía 5 secretos: 3 de pruebas de 1 hora de la fase 1 (todavía vigentes), el del
extractor CDC de la fase 2 y uno huérfano de un intento fallido. Los secretos cuentan para el límite
hasta que se borran, aunque estén vencidos o sin uso.

Con un SP compartido por 4 productores (CDC, SEC EDGAR, GDELT, enriquecimiento), cada uno con su
secreto y su rotación (el secreto nuevo convive con el viejo hasta el cambio), el límite de 5 se
alcanza en la operación normal.

## Decisión
**Un SP por productor**, creado por Terraform (`infra/databricks/producers.tf`), todos con los mismos
grants mínimos: entitlement `workspace_access`, `USE_CATALOG` sobre `entity360`, `USE_SCHEMA` sobre
`landing` y `READ_VOLUME`/`WRITE_VOLUME` sobre `landing.raw`.

| SP | Productor | Dónde vive su secreto |
|---|---|---|
| `entity360-producer` (recurso `producer_cdc`; el nombre no se puede cambiar in-place, ver Pendiente) | Extractor CDC (fase 2) | Administrador de credenciales de Windows (`keyring`) |
| `entity360-producer-sec-edgar` | Lambda de entrega SEC EDGAR (fase 3) | AWS Secrets Manager |
| (fase 4) | GDELT | GCP Secret Manager |
| `entity360-producer-enrichment` | Container de enriquecimiento (fase 5) | GitHub Secrets |

## Consecuencias
- **Límite de secretos:** cada SP usa 1 o 2 (durante la rotación). El límite de 5 deja de ser un
  riesgo.
- **Auditoría:** los logs de acceso de Unity Catalog y los archivos del volume muestran qué productor
  escribió cada cosa.
- **Aislamiento:** revocar o rotar el secreto de un productor no afecta a los demás; un secreto
  filtrado compromete un solo productor.
- **Costo:** más recursos en Terraform (1 SP + 3 grants por productor). Sin costo monetario.
- Los grants siguen sin dar lectura a ningún schema fuera de `landing.raw` (ADR 0001).

## Pendiente: el nombre del SP del CDC
El objetivo era renombrar `entity360-producer` a `entity360-producer-cdc`. Resultado (2026-09-26):

- El recurso de Terraform ya se llama `producer_cdc` (grants `cdc_*`, outputs `producer_cdc_sp_*`),
  movido con bloques `moved`: sin destruir nada, mismo `application_id`, mismo secreto.
- **El `display_name` no se puede cambiar.** El plan lo muestra como update in-place y el apply
  reporta "Modifications complete", pero el nombre queda igual y el plan siguiente lo vuelve a
  proponer. Un `PATCH` SCIM directo (`service-principals patch`, `replace displayName`) responde OK y
  tampoco lo cambia. Causa: en Free Edition el SP es un principal de **cuenta** (identity
  federation) y la API del workspace ignora en silencio los cambios de sus atributos de cuenta; la
  consola de cuenta no está disponible.
- El código quedó con el nombre real para que el plan no tenga cambios permanentes.

Queda por decidir (con OK, porque borra un SP):
1. **Reemplazo:** SP nuevo `entity360-producer-cdc` con los mismos grants, secreto nuevo en el
   keyring (`credenciales.py configurar`), extractor y smoke test contra el nuevo, y después borrar
   `entity360-producer` (se lleva su secreto).
2. **Dejar el nombre:** el aislamiento, la auditoría y el límite de secretos ya se cumplen (cada
   productor tiene su SP); solo queda el nombre heredado de la fase 1.
