# 01 — Arquitectura

## Vista general

```text
 FUENTES (cada una en "otro sistema" de la organización)           CONVERGENCIA
 ──────────────────────────────────────────────────────           ────────────
 ON-PREM (container local)
   SQL Server "legacy"  ← carga de GLEIF (entidades legales, LEI)
        │ CDC                                           ──push──┐
 AWS                                                             │
   EventBridge Scheduler → Lambda → S3 (SEC EDGAR)     ──push──┤   Databricks (Free Edition)
 GCP                                                             ├─► UC Volume landing
   Cloud Scheduler → Cloud Run Job → BigQuery (GDELT) → GCS ─push┤        │
 CONTAINER de enriquecimiento                                    │   Bronze → Silver → Resolución
   OpenSanctions + Wikidata                             ──push──┘   de identidades → Gold (dbt)
                                                                          │
                                           ┌──────────────────────────────┼────────────────┐
                                           ▼                              ▼                ▼
                                    Dashboard AI/BI                Genie space        Snowflake
                                    (vista 360)               (preguntas en lenguaje   (modelers)
                                                               natural sobre Gold)
 Airflow (local, Docker) = plano de control:
   CDC → extracciones → contratos (Soda) → job Databricks → dbt (Cosmos) → Snowflake → checks
```

## Por qué cada pieza
| Pieza | Motivo |
|---|---|
| SQL Server + CDC | El sistema legacy on-prem. Muestra el patrón más pedido: sacar cambios de una base transaccional sin romperla. |
| AWS | Otro sistema de la organización: la extracción de presentaciones SEC EDGAR, programada, con respaldo en S3. |
| GCP | Las señales casi en tiempo real: GDELT (eventos de noticias cada 15 minutos) vive como dataset público en BigQuery. |
| Container de enriquecimiento | Fuentes de riesgo y de vínculos (OpenSanctions, Wikidata). Corre igual en cualquier lado. |
| Databricks | Convergencia, trabajo pesado en Spark, resolución de identidades, gobierno con Unity Catalog, consumo con dashboard y Genie. |
| Soda Core + dbt | El "Data Contract Enforcer": contratos en la llegada (Soda) y en los modelos (dbt), cuarentena y alertas. |
| Airflow | Orquesta lo que vive fuera de Databricks. Si todo estuviera adentro, alcanzarían los Jobs de Databricks; acá no. |
| Snowflake | El warehouse del equipo de modelers: el escenario real de "empresa con dos plataformas". |
| Iceberg | Formato abierto para que Snowflake lea sin copiar, si el spike lo habilita. |

## Por qué estas fuentes (y cómo se pisan)
- **GLEIF:** identificador global de entidades legales (LEI), con nombre legal, país,
  dirección y relaciones de matriz/filial.
- **SEC EDGAR:** empresas que presentan ante la SEC, identificadas por CIK, con nombres
  históricos y datos de contacto.
- **Wikidata:** tiene propiedades con LEI y CIK para muchas empresas. Sirve como
  **verdad de referencia parcial** para medir la calidad de la resolución de identidades.
- **OpenSanctions:** entidades con riesgo (sanciones, personas expuestas), con nombres y
  alias.
- **GDELT:** menciones de organizaciones en noticias globales, con tono.

Ninguna comparte un identificador con todas las demás: por eso hace falta resolver
identidades. Esa es la parte central del proyecto.

## Universo acotado
No se carga el mundo entero. El universo inicial lo define el spike, por ejemplo: empresas
argentinas con LEI + empresas argentinas que cotizan en EE. UU. y presentan ante la SEC +
un conjunto de control de otros países. Se amplía después si el costo y la cuota lo
permiten.

## Decisión clave: modelo PUSH hacia un UC Volume
Todos los productores empujan archivos a un Unity Catalog Volume con la Files API de
Databricks (`PUT /api/2.0/fs/files/Volumes/...`). Motivo: la Free Edition usa default
storage y tiene salida a internet restringida. Cada productor escribe primero en su propio
almacenamiento (respaldo en su nube) y después empuja.

## Contrato común de landing
`/Volumes/entity360/landing/raw/<fuente>/ingest_date=YYYY-MM-DD/<fuente>_<timestamp_utc>.<ext>`
más un `_manifest_<timestamp_utc>.json` por lote, con el mismo timestamp que el archivo de
datos (así dos lotes del mismo día no se pisan): fuente, archivo, registros, hash,
timestamp de extracción, versión del productor. Airflow usa los manifests como señal de
llegada. El manifest se sube **después** del archivo de datos.

## Estructura del repo
```text
entity360-multicloud-databricks/
├── reglas/            # estas reglas
├── docs/              # arquitectura, decisiones (ADR), fuentes, manual-steps, destroy
├── infra/{databricks,aws,gcp,snowflake}/   # Terraform
├── legacy/            # SQL Server en Docker, carga inicial de GLEIF, CDC
├── producers/{aws_sec_edgar,gcp_gdelt,container_enrichment,cdc_extractor}/
├── databricks/        # Bronze, Silver, resolución de identidades
├── dbt/               # Gold, contratos, tests
├── contracts/         # checks de Soda Core por fuente
├── airflow/           # docker-compose, DAGs
├── consumption/       # dashboard AI/BI, instrucciones de Genie
├── spike/             # evidencia del spike
├── referencias/       # repos viejos, ignorada por git
└── tests/
```
