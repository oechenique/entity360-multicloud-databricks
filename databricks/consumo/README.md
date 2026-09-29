# Consumo: dashboard "Entity 360" y espacio de Genie (fase 10, regla 12)

La data curada, gobernada y documentada ya vive en Unity Catalog: el dashboard la muestra y Genie
demuestra que está lista para preguntarle en lenguaje natural. Ponerle un agente encima es el último
paso.

| Pieza | Fuente versionada | Despliegue |
|---|---|---|
| Dashboard AI/BI "Entity 360" | `generar_dashboard.py` → `entity360.lvdash.json` | Terraform: `infra/databricks/consumo.tf` (`databricks_dashboard`, publicado) |
| Espacio de Genie "Entity 360" | `genie/espacio.json` → `genie/serialized_space.json` | `genie.py desplegar` (el provider no tiene recurso para Genie) |
| Resultados de dbt | `dbt/macros/registrar_resultados.sql` (on-run-end) | tabla `ops.dbt_resultado` (Terraform) |
| Precisión y recall de la resolución | `databricks/resolucion/calibracion/resultados_*.json` | `calibrar.py --publicar` → `ops.calidad_resolucion` (Terraform) |

## Dashboard
Tres páginas, 25 datasets (todos probados contra el warehouse):
1. **Entity 360.** Un buscador de empresa (lista con búsqueda sobre las 1.136 entidades) fija el
   parámetro `empresa` de ocho datasets: golden record con la procedencia de cada atributo, fuentes de
   las que sale, duplicados resueltos (pares unidos, con decisión, puntaje y señales), casos en revisión
   que la tocan, menciones y tono en noticias (GDELT), riesgo (OpenSanctions) e historial de cambios del
   CDC del legacy.
2. **Panorama.** Entidades, registros fusionados, LEI duplicados, listas de riesgo; entidades más
   consolidadas; noticias de los últimos 30 días; alertas de riesgo; cambios recientes del legacy.
3. **Salud de la plataforma.** Frescura por fuente (horas desde el último lote y estado de la última
   `dbt source freshness`), latencia de punta a punta (extracción → landing → Bronze → golden), volumen
   por día y fuente, lotes en cuarentena o descartados, filas en cuarentena de Silver, tests y modelos
   de dbt, decisiones de la resolución, casos en revisión y precisión/recall por versión con su IC.

Los duplicados resueltos y la revisión leen el schema `resolution` (no Gold): son la explicación de por
qué el golden record es lo que es.

```powershell
python databricks\consumo\generar_dashboard.py      # regenera el JSON
cd infra\databricks; terraform plan -out=d.tfplan; terraform apply d.tfplan
```

## Genie
Espacio sobre las cinco tablas de Gold, con:
- **Descripciones de columnas:** las de `dbt/models/gold/gold.yml` (55 columnas), las mismas que dbt
  persiste como comentarios en Unity Catalog; sinónimos y entity matching para nombres, países, fuentes.
- **Instrucciones:** el modelo (todo se une a `dim_entity` por `entity_id`), cómo buscar una empresa por
  nombre en todas las fuentes, códigos de país, qué significa sancionada y en listas de riesgo, el tono
  de GDELT, las claves del JSON `detalle` del CDC y cómo comparar versiones, y la atribución de licencias.
- **Joins** de las cuatro tablas de hechos con `dim_entity`, **4 ejemplos de SQL** y **5 preguntas de
  ejemplo**.

```powershell
.venv\Scripts\python.exe databricks\consumo\genie.py desplegar   # crea o actualiza, por título
.venv\Scripts\python.exe databricks\consumo\genie.py probar      # guarda genie/pruebas.json
```

### Prueba con 5 preguntas reales (2026-09-29)
Preguntas distintas de las de ejemplo; el SQL que generó Genie y las filas que devolvió están en
`genie/pruebas_1.json` (primera versión de las instrucciones) y `genie/pruebas.json` (versión final).
Cada respuesta se verificó con una consulta propia.

| # | Pregunta | Corrida 1 | Corrida 2 (final) |
|---|---|---|---|
| 1 | ¿Cuáles son las empresas argentinas sancionadas cuyo vínculo con la lista es por LEI? | Correcta: 1 (華爲技術投資有限公司, LEI 213800DUQGMJ7FWYJ659) | Correcta |
| 2 | ¿De qué fuentes sale Telecom Argentina y cuál es su CIK? | Correcta: 5 fuentes, CIK 932470 | Correcta |
| 3 | ¿Qué empresas tuvieron cobertura con tono negativo en septiembre de 2026 y cuántas menciones? | Correcta: 4 empresas (Galicia 5, Macro 2, MercadoLibre 1, TGS 1) | Correcta |
| 4 | ¿Qué empresas cambiaron de nombre en el legacy y cuál era el nombre anterior? | **Incorrecta: "ninguna".** Usó la clave `$.nombre` (es `nombre_legal`) y calculó el `LAG` después de filtrar los `update`, así que nunca veía la versión anterior | **Correcta** tras documentar las claves de `detalle` y el patrón LAG → filtro: VALCEREAL SA → VALCEREAL S. A. |
| 5 | ¿Cuántas empresas tienen LEI duplicados fusionados, por país? | Correcta: 65, todas AR | Correcta |

Lo que muestra la prueba: con el modelo documentado, Genie resuelve bien búsquedas, joins y filtros;
donde falla es en la **estructura de un JSON que no está descripta**. La corrección fue de datos
(documentación), no de modelo. La pregunta 1 devuelve una entidad con nombre en chino y país AR: es el
dato real de GLEIF para ese LEI, no un error de Genie. Las menciones de Banco Galicia caen en su entidad
de solo GDELT (error conocido, `README.md`).

## Límites
- Free Edition: un solo warehouse; el dashboard se publica con las credenciales del dueño.
- La primera llamada de la prueba devolvió `FAILED` sin detalle y la repetición funcionó: `genie.py`
  ahora guarda el `error` de cada mensaje.
- Las señales de GDELT son pocas (15 menciones) mientras Airflow esté apagado: se acumulan en el landing
  y entran con la próxima corrida del DAG.
