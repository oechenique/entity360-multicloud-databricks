# 02 — Fase 0: Spike de validación

Objetivo: responder con evidencia lo que puede cambiar el diseño. Todo lo que se cree
vive en `spike/` y se destruye al final, salvo el informe.

**No abrir el trial de Snowflake en esta fase** salvo que se cumpla la condición del
punto 4. El trial dura 30 días desde el alta.

## A. Infraestructura (independiente del dominio)

### 1. Push a UC Volume desde afuera
- Catálogo `entity360`, schema `landing`, volume `raw`. Subir un archivo con la Files API
  desde la PC y leerlo con Spark.
- Auth: primero PAT de vida corta; después intentar un service principal con OAuth M2M.

### 3. Iceberg gestionado en Free Edition
- Tabla `USING ICEBERG`, escritura y consulta por el endpoint Iceberg REST de Unity
  Catalog con PyIceberg desde la PC.
- Resultado esperado según la documentación: sin credential vending sobre default storage.
  Confirmarlo.

### 4. Salir del default storage
- Storage credential + external location sobre un bucket S3 propio, y catálogo con
  `MANAGED LOCATION` ahí. Probar lectura/escritura desde serverless.
- Si funciona → abrir el trial de Snowflake y probar una catalog integration
  `ICEBERG_REST` con `VENDED_CREDENTIALS` (Camino A de la regla 11).
- Si no → Camino B. No abrir el trial todavía.

### 5. Salida a internet de la Free Edition
- Verificar si la verificación con LinkedIn está activa y qué cambia.

### 6. Consumo en Free Edition
- Confirmar que se puede crear un dashboard AI/BI y un espacio de Genie sobre tablas del
  catálogo, y sus límites.

## B. Fuentes y legacy

### 7. SQL Server legacy con CDC
- Levantar SQL Server en Docker (edición Developer: el CDC necesita el SQL Server Agent,
  que la edición Express no trae; variable `MSSQL_AGENT_ENABLED=true`).
- Habilitar CDC en una tabla de prueba, hacer inserts/updates y leer los cambios con
  `cdc.fn_cdc_get_all_changes_*`.

### 8. GLEIF
- Descargar el archivo "golden copy" más reciente (CSV). Medir tamaño y cantidad de
  registros para el universo acotado (por ejemplo, país AR). Anotar licencia.

### 9. SEC EDGAR
- Consultar el JSON de submissions de 2 o 3 empresas argentinas que presentan ante la SEC.
- La SEC exige un `User-Agent` con nombre y mail, y limita la cantidad de requests por
  segundo: respetarlo.

### 10. GDELT en BigQuery
- Consultar la tabla de eventos **particionada**, siempre con filtro de partición y un
  `dry run` antes para ver cuántos bytes escanearía. Sin filtro puede escanear terabytes y
  comerse la cuota gratuita.
- Medir cuántas menciones de organizaciones del universo aparecen por día.
- Alternativa si BigQuery no conviene: los archivos crudos que GDELT publica cada 15 min.
- **Nota:** requiere proyecto de GCP. Si todavía no existe, dejar esta pregunta pendiente
  y avisar.

### 11. OpenSanctions y Wikidata
- OpenSanctions: descargar el dataset consolidado y anotar la licencia (uso no comercial
  con atribución: un portfolio encaja, pero documentarlo).
- Wikidata: consulta SPARQL de empresas con LEI (P1278) y/o CIK (P5531) del universo.
  Medir cuántas hay: es la verdad de referencia para evaluar el matching.

## Entregable
`spike/INFORME.md`: pregunta | resultado (✅/❌/⏳) | evidencia | impacto en el diseño.
Más: universo recomendado (con cantidades) y camino A o B para Snowflake. Frenar y esperar
OK. Destruir los recursos del spike, con confirmación, antes de la fase 1.
