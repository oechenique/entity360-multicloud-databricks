# ADR 0012 — La catalog integration de Snowflake va por script, no por Terraform

- **Estado:** aceptado (fase 9, planificación, 2026-09-29). Decisión de Gastón.
- **Relacionado:** principio 3 (Terraform) y 4 (sin claves estáticas), ADR 0002 (secretos de los SP fuera
  del state), `docs/fase9-plan.md` §2.

## Contexto
La catalog integration `ICEBERG_REST` de Snowflake contra Unity Catalog se autentica con OAuth M2M del SP
`entity360-snowflake`: lleva su `client_secret`. El provider de Snowflake la soporta
(`snowflake_catalog_integration_iceberg_rest`), pero todo lo que recibe un recurso termina en el
state de Terraform, aunque sea `sensitive`. Hasta acá ningún secreto del proyecto pasó por un state: los
de los SP se crean con la CLI y viven en el llavero de Windows o en el secret manager de cada nube.

## Decisión
- La **catalog integration** y la **base catalog-linked** que depende de ella salen de Terraform y las
  crea `snowflake/integracion.py`, que lee el secreto del llavero (servicio `entity360-snowflake`).
- El script es **idempotente**: `CREATE ... IF NOT EXISTS`; si la integración existe con la misma
  configuración no la toca; si existe con otra, falla sin cambiar nada (recrearla es un `DROP`, a mano y
  con OK); `--rotar-secreto` es solo un `ALTER ... SET REST_AUTHENTICATION`. Corre
  `SYSTEM$VERIFY_CATALOG_INTEGRATION` al final.
- **El secreto no sale:** no se imprime ni se loguea (el logger del conector queda en WARNING, que no
  muestra el SQL) y un error de Snowflake que cite el statement se propaga con el secreto reemplazado por
  `***`. Tests con mocks en `tests/snowflake/test_integracion.py`.
- En Terraform queda todo lo que no tiene secretos: resource monitor, warehouse, roles, base de marts y
  el external volume del Camino A2 (un rol IAM, sin claves).

## Consecuencias
- Dos pasos en vez de uno: `terraform apply` en `infra/snowflake` y después `integracion.py crear`. El
  destroy es al revés: `DROP` de la base catalog-linked y de la integración, después `terraform destroy`
  (`docs/destroy.md`).
- Terraform no ve la integración: un cambio a mano en Snowflake no aparece en un `plan`. El script lo
  detecta al compararla con `DESC CATALOG INTEGRATION` y se niega a seguir.
- Exposición residual a verificar en el primer uso: si `QUERY_HISTORY` guarda el texto del `CREATE` con
  el secreto a la vista, queda visible para quien lea el historial de la cuenta (ACCOUNTADMIN por
  defecto) hasta que el secreto venza (90 días).
