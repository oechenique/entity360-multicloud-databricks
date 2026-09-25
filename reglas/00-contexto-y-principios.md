# 00 — Contexto y principios

## El proyecto
**Repo:** `entity360-multicloud-databricks`
**Idioma:** todo el desarrollo, la documentación y los commits en español. La traducción
al inglés se hace al final, junto con el resto del portfolio.

Sexto y último proyecto del portfolio de Data Engineering de Gastón.

**El problema (real, de la industria):**
> Una organización tiene sus datos repartidos en sistemas legacy on-premise y en varias
> nubes. La misma entidad aparece en diez sistemas, con nombres e identificadores
> distintos, duplicada y sucia. Necesita en 2 meses una base confiable para que modelen
> los analistas y en 6 meses poder poner agentes encima. Además quiere señales casi en
> tiempo real para marketing y riesgo.

**La solución que construye este repo:** una plataforma que consolida esas fuentes, resuelve
identidades en un **golden record** (una fila confiable por entidad), aplica contratos de
datos, gobierna todo en Unity Catalog y entrega data curada lista para consumir: dashboard,
Genie y un warehouse para los modelers.

**Las entidades son empresas reales** y las fuentes son registros públicos reales que se
pisan entre sí. El desorden no se inventa: ya existe.

**Cierre del portfolio:** el mensaje final es "te dejé la data curada, documentada,
gobernada y viviendo en la nube; ponerle un agente es lo más fácil que te queda". No se
construye otro agente.

## Principios no negociables
1. **Data real, siempre.** Cero datos inventados, simulados o sintéticos. Cargar data real
   en un SQL Server para que haga de sistema legacy es una decisión de arquitectura, no de
   datos: se documenta así en el README.
2. **Cada herramienta tiene un motivo.** Si no se puede explicar en una oración por qué
   una pieza está, no va.
3. **Terraform desde el día 1** para todo lo que lo soporte. Lo que no, en
   `docs/manual-steps.md`.
4. **Sin claves estáticas** en código ni en el repo. Secretos en el secret manager de cada
   nube o en GitHub Secrets. `.gitignore` cubre `*.tfstate*`, `.env`, `profiles.yml`.
5. **Alertas de presupuesto antes de crear cualquier recurso** en AWS y GCP.
6. **Idempotencia.** Correr cualquier proceso dos veces no duplica datos.
7. **Destroy documentado** en `docs/destroy.md`, escrito junto con la infra.
8. **Licencias respetadas.** Cada fuente con su licencia y atribución en `docs/fuentes.md`.
9. **Sin datos identificatorios en el repo.** Docs, evidencia y código versionado usan
   placeholders: `<AWS_ACCOUNT_ID>`, `<WORKSPACE_URL>`, `<METASTORE_ID>`,
   `<DATABRICKS_ACCOUNT_ID>`, `<GCP_PROJECT_ID>`, `<DATABRICKS_USER_EMAIL>`,
   `<CONTACT_EMAIL>`. Los valores reales van en archivos ignorados por git (`.env`,
   `terraform.tfvars`, con su `.example` versionado) o en variables de entorno. La evidencia
   se sanea antes de guardarla.

## Forma de trabajo con Claude Code
- Una fase por vez, en el orden de estas reglas. Al terminar cada fase: resumen, cómo
  verificarlo, y **frenar** a esperar OK.
- **Nunca** ejecutar comandos destructivos (`destroy`, `delete`, `drop`, `rm -rf`,
  `--force`) sin confirmación explícita, aunque el auto mode lo permita.
- Entorno local: **Windows 11 + PowerShell**.
- **AWS:** usar SIEMPRE `--profile tesseract` (o `$env:AWS_PROFILE="tesseract"`), nunca el
  perfil default. Si las credenciales vencen, pedirle a Gastón que corra
  `aws login --profile tesseract`.
- **Región de AWS para storage de Unity Catalog: `us-east-2`**, la del metastore de Free
  Edition (buckets de `MANAGED LOCATION`, rol IAM de la storage credential). El resto de los
  recursos de AWS sigue la región de su regla (por ejemplo, la 05).
- Lo que sea "a validar" se valida con evidencia (salida de comando, query), no con
  suposiciones.
- Commits chicos y descriptivos por fase. Push solo con OK.

## Repos de referencia (solo inspiración, no alcance)
Si existen en `referencias/` (ignorada por git), se pueden leer para tomar estilo y
aprendizajes. No se copia código sin decirlo.
