# 08 — Fase 6: Bronze, Silver y resolución de identidades

## Bronze
- Auto Loader con `Trigger.AvailableNow` sobre el volume, una tabla por fuente. Payload
  crudo + metadatos del manifest. En CDC, conservar operación y LSN.

## Silver
- Limpieza y tipado por fuente. Normalización de nombres (mayúsculas, acentos, sufijos
  societarios como S.A., SRL, Inc., Corp.), países (ISO), direcciones básicas.
- CDC aplicado: tabla vigente con historial (SCD tipo 2) sobre los cambios del legacy.
- Registros que no cumplen el esquema → `_quarantine` con el motivo.

## Resolución de identidades (el corazón del proyecto)
1. **Matching determinístico** por identificadores compartidos (LEI, CIK) donde existan.
2. **Blocking** para no comparar todo contra todo (por país + prefijo normalizado del
   nombre, por ejemplo).
3. **Matching difuso** dentro de cada bloque con reglas explicables (similitud de nombre,
   país, ciudad, sitio web) y un puntaje. Sin modelos de ML: reglas auditables.
4. **Clusters** de registros que son la misma entidad → `entity_id` estable.
5. **Golden record** con reglas de supervivencia por atributo (qué fuente gana para el
   nombre legal, cuál para la dirección, etc.), documentadas.
6. **Evaluación contra Wikidata** como verdad de referencia parcial: precisión y recall
   del matching, publicados en el README. Esa métrica es lo que diferencia el proyecto.
7. Casos dudosos (puntaje intermedio) → tabla de revisión, no se fuerzan.

Tablas en formato Iceberg gestionado donde sea posible.
