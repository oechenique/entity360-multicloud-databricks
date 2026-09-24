# Informe del spike (Fase 0)

Estado: **en curso** (parte A).

## Resultados
| # | Pregunta | Resultado | Evidencia | Impacto en el diseño |
|---|---|---|---|---|
| 1a | Push a UC Volume desde afuera con PAT + lectura con Spark | ✅ | `evidencia/a1-push-pat.txt`, `evidencia/a1-read-spark.txt` | El modelo push de la regla 01 funciona tal cual. |
| 1a' | Crear el catálogo con Terraform sobre default storage | ❌ | `evidencia/a1-catalogo-default-storage.txt` | Catálogo por SQL + `terraform import`; paso manual en `docs/manual-steps.md`. |
| 1b | Push con service principal (OAuth M2M) | ⏳ | | |
| 3 | Iceberg gestionado + PyIceberg por REST | ⏳ | | |
| 4 | Salir del default storage (S3 propio) | ⏳ | | |
| 5 | Salida a internet de Free Edition | ⏳ | | |
| 6 | Dashboard AI/BI y Genie | ⏳ | | |
| 7–11 | Parte B | ⏳ | | GDELT (10) pendiente: no existe proyecto GCP. |

## Decisiones
| ID | Decisión | Motivo |
|---|---|---|
| D1 | El catálogo `entity360` se crea por SQL y se importa a Terraform (paso manual documentado). | La API de UC no acepta default storage en Free Edition. |
| D2 | Manifest por lote como `_manifest_<timestamp_utc>.json` (regla 01 actualizada). | Con un `_manifest.json` fijo, dos lotes del mismo día en la misma partición se pisan. |
| D3 | Los archivos de datos se suben en JSON Lines (`.jsonl`) cuando la fuente es JSON. | `read_files` los lee directo, un registro por fila. |
