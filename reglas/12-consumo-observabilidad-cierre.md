# 12 — Fase 10: Consumo, observabilidad y cierre

## Consumo (el producto final)
- **Dashboard AI/BI "Entity 360":** buscador de empresa → golden record, fuentes de las
  que sale, duplicados resueltos, historial de cambios, señales de noticias, alertas de
  riesgo.
- **Espacio de Genie** sobre Gold, con instrucciones, ejemplos de preguntas y
  descripciones de columnas. Demuestra que la data está lista para lenguaje natural.
- El mensaje: la data curada, gobernada y documentada ya vive en la nube; el agente es el
  último paso y el más fácil.

## Observabilidad de la plataforma
- Frescura y volumen por fuente, lotes en cuarentena, estado de contratos y tests,
  métricas de la resolución (precisión, recall, casos en revisión), latencia de punta a
  punta.

## Cierre
- README en español: el problema, la historia, el diagrama, el porqué de cada pieza, las
  métricas de calidad, las limitaciones (y cómo se resolvieron), cómo levantarlo.
- ADRs en `docs/decisions/`.
- `docs/fuentes.md` con licencias y atribuciones.
- `docs/destroy.md` probado: Snowflake, GCP, AWS, Databricks, legacy local.
- Capturas y video de demo.

## Fase opcional (después del cierre)
- Debezium Server para el CDC.
- Ampliar el universo de entidades.
