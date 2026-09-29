# ADR 0010 — Resolución de identidades por reglas auditables, calibrada contra un set curado a mano

- **Estado:** aceptado (fase 6, 2026-09-27; v2.1 el 2026-09-29).
- **Relacionado:** regla 08, D11 del spike, ADR 0004 (medallion en PySpark),
  `databricks/resolucion/calibracion/INFORME.md`.

## Contexto
Ninguna fuente comparte un identificador con todas las demás: GLEIF tiene LEI, la SEC tiene CIK, GDELT
tiene un nombre y OpenSanctions a veces un LEI. Hace falta decidir qué registros son la misma empresa y
poder explicar cada decisión. Wikidata cubre 3 a 5 de los 16 emisores de la SEC y el 1 % del universo
(spike, B.11): no alcanza como verdad de referencia.

## Decisión
- **Reglas, no ML:** un LEI o un CIK compartido une sin puntaje (salvo que venga de Wikidata, que es
  señal); si no, blocking (país + prefijo, tokens raros, ticker, dominio) y un puntaje por señales con
  pesos fijos: nombre, país, ciudad, ticker, dominio, fondo contra empresa, series distintas, gemelo de
  LEI. Aceptar desde 70, revisar entre 50 y 69. Cada par guarda la contribución de cada señal.
- **Restricciones duras:** nunca dos LEI firmes ni dos CIK en una entidad; los empates entre candidatos
  de LEI distintos van a revisión, no se deciden por orden alfabético.
- **Medición contra un set curado a mano (D11):** 59 registros y 60 pares etiquetados con evidencia,
  partidos por estrato en calibración y evaluación con semilla fija. Precisión y recall con intervalo de
  Wilson. La v1 se midió a ciegas; las versiones siguientes se reportan como **no ciegas**.
- **Lo dudoso no se fuerza:** queda en `resolution.revision` (revisar, conflicto, empate).

## Consecuencias
- v1 (ciega) 0,913 / 0,955 en evaluación; v2.1 (no ciega) 1,000 / 1,000 en evaluación y 1,000 / 0,978
  en el set completo. Con 57 unidades de evaluación los intervalos son anchos ([0,851–1,000]) y se
  publican así.
- Los pesos no los movió la grilla: con 62 unidades de calibración, las diferencias son ruido.
- Un caso conocido queda en revisión a propósito (Banco Galicia): unirlo exigía suponer un país.
- Con un universo grande, el blocking y los clusters pasan a Spark distribuido; el puntaje ya lo es.
