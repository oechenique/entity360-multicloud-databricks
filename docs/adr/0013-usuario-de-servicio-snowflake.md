# ADR 0013 — Usuario de servicio de Snowflake con ACCOUNTADMIN, solo durante el proyecto

- **Estado:** aceptado (fase 9, 2026-09-29). Decisión de Gastón, con condiciones.
- **Relacionado:** ADR 0012 (catalog integration por script), principio 4 (sin claves estáticas en el
  repo), `docs/manual-steps.md` §14–15, `docs/destroy.md` (Snowflake).

## Contexto
Terraform (`infra/snowflake`) y `snowflake/integracion.py` necesitan un principal en Snowflake. Crear un
resource monitor y una catalog integration exige ACCOUNTADMIN. El trial es de una sola persona y dura 30
días. El provider de Terraform lee la clave privada como contenido PEM (`private_key` en
`~/.snowflake/config`), no como ruta.

## Decisión
- **`ENTITY360_TF`**: usuario `TYPE = SERVICE`, sin contraseña, key pair RSA 2048, rol **ACCOUNTADMIN**.
  Lo crea Gastón en Snowsight con un único SQL que lleva solo la clave pública (`snowflake/cuenta.py
  claves`). Existe **solo mientras dura el proyecto**: el destroy lo borra al final.
- **`ENTITY360_DBT_SVC`**: usuario de servicio con el rol `ENTITY360_DBT` (solo los marts), creado por
  Terraform con su clave pública.
- **Claves privadas** en `~/.snowflake/keys/*.p8`, sin frase, con acceso restringido al usuario de
  Windows (`icacls /inheritance:r /grant:r <usuario>:F`). La de `ENTITY360_TF` también está en
  `~/.snowflake/config` (perfil `entity360`), con la misma restricción, porque el provider no acepta una
  ruta. Nada de esto va al repo; el script nunca imprime las privadas.
- **El account identifier real no va al repo:** en los documentos, `<ORG>-<CUENTA>`; el real vive solo en
  `~/.snowflake/config` y `~/.snowflake/connections.toml`.
- Las dos claves figuran en la tabla de secretos (`manual-steps.md` §5): no vencen y se rotan a mano
  (`ALTER USER ... SET RSA_PUBLIC_KEY_2`, cambiar la clave local y después `UNSET RSA_PUBLIC_KEY`).

## Consecuencias
- Quien tenga la sesión de Windows de la PC tiene ACCOUNTADMIN sobre el trial. Aceptable para un trial
  personal de 30 días sin datos propios (Gold se lee de Unity Catalog, no se copia); en una cuenta de
  empresa serían roles separados (SYSADMIN para objetos, SECURITYADMIN para grants, un rol propio con
  `CREATE INTEGRATION`) y la clave en un secret manager.
- El destroy de Snowflake termina con `DROP USER` de los dos usuarios y el borrado de las claves y del
  perfil locales (`docs/destroy.md`).
