# Calibración y evaluación de la resolución de identidades (2026-09-27)

Set curado a mano (D11): parte A (59 registros) + parte B (60 pares), sin `incierto`. Partición por
estrato (A: fuente; B: estrato del generador), semilla 20260927: **62 unidades de calibración y 57 de
evaluación**. Script: `calibrar.py` (usa `identidades.senales`/`decidir`, el mismo código del job);
números completos: `resultados_v1.json` y `resultados_v2.json`.

| Versión | Qué es | ¿Evaluación ciega? |
|---|---|---|
| **v1** | Resolución inicial (commit `51ee671`) | **Sí**: nadie miró los errores antes de medir |
| **v2** | v1 + las 4 correcciones de abajo, con los mismos pesos | **No**: las correcciones salieron de mirar los errores de todo el set, incluida la mitad de evaluación |

## Resultados (Wilson 95 %)

**Mitad de evaluación (57 unidades):**

| | Precisión | Recall | VP / FP / FN |
|---|---|---|---|
| **v1 (ciega)** | **0,913** [0,732–0,976] | **0,955** [0,782–0,992] | 21 / 2 / 1 |
| v2 (no ciega) | 1,000 [0,851–1,000] | 1,000 [0,851–1,000] | 22 / 0 / 0 |

**Set completo (119 unidades; la mitad de calibración también la vio el diagnóstico):**

| | VP / FP / FN | Precisión | Recall |
|---|---|---|---|
| v1 | 43 / 4 / 3 | 0,915 | 0,935 |
| v2 | 44 / 0 / 2 | 1,000 | 0,957 |

**Recall del blocking** (parte A, el LEI correcto es candidato del registro): 22/22 en v1 y en v2
[0,851–1,000], aunque la v2 genera menos pares (4699 contra 5011).

**Grilla de pesos:** en la v1, los pesos iniciales empatan en el máximo F1 de calibración (6561 de
14.580 combinaciones). En la v2, la grilla propone bajar el umbral de aceptación de 70 a 60: gana
0,002 de F1 en calibración y **empeora la evaluación** (un falso positivo). **Se deja 70**: con 62
unidades, esa diferencia es ruido.

## Las 4 correcciones (v2) y sus tests

| Causa (v1) | Corrección | Test |
|---|---|---|
| A016, A058: la clave `VIST` de GDELT unía la matriz mexicana de Vista con su filial argentina, con 70 puntos gracias al país AR que `resolucion.py` suponía | Las claves de GDELT van sin país | `test_v2_gdelt_sin_pais_no_une_matriz_con_filial`, `test_resolucion_no_supone_pais_para_gdelt` |
| A028: los alias "Ute" / "The Joint Venture" de una UTE de OpenSanctions empataban en 100 con cualquier nombre con "UTE" | `token_set_ratio` solo con ≥ 2 tokens significativos; nombres hechos solo de tokens genéricos (UTE, joint venture, consorcio) se ignoran | `test_v2_alias_genericos_no_unen_utes_distintas`, `test_v2_un_solo_token_no_usa_token_set` |
| B019, B037, B045: el LEI anulado empataba en 75 con su gemelo y con otra entidad, y el orden de las claves decidía | Señal `gemelo_lei` (+30: misma base de 18 caracteres, reemisión de la LOU argentina) y los empates entre candidatos de LEI firmes distintos van a revisión | `test_v2_gemelo_de_lei_gana_al_empate`, `test_v2_empate_con_lei_firmes_distintos_va_a_revision` |
| B038: el ítem de Wikidata de Flow (una marca) trae el LEI de Cablevisión Holding y los unía sin puntaje | Un LEI o CIK de Wikidata es la señal `id_wikidata` (+40): no une, no veta y no cuenta para la restricción | `test_v2_lei_de_wikidata_es_senal_no_union` |

## Uniones falsas fuera del set que la v2 corrigió
Pares que nadie etiquetó, pero que la v1 unía y son claramente entidades distintas:
- **Banco Central de la República Argentina** (LEI anulado `579100KKDDKIFCBKB036`) con **"República
  Argentina"** (el Estado, `549300KPBYGYF7HCHO27`).
- **Banco Provincia del Neuquén** (LEI anulado `579100KKDKKEFHBKE017`) con **"Provincia de Neuquén"**
  (`549300X5HUL4FRDNBN35`).
- **Industrial and Commercial Bank of China (Argentina)** (LEI anulado `579100JKDIEEHGEKH006`) con
  **Banco Industrial S.A.** (`579100FKDJKFGJCIJ027` y `579100FKDJKFGJCIJ071`).

En los tres casos, la v2 une el LEI anulado con su gemelo vigente.

## Lo que la v2 empeoró (mitad de calibración)
Dos uniones correctas de la v1 se perdieron. Las dos están en la mitad de calibración, así que la
evaluación no las ve:
- **A006, Cresud (SEC, "CRESUD INC")**, que ya no se une a Cresud S.A.C.I.F.y A. Causa: la regla de
  ≥ 2 tokens. "CRESUD" es un solo token, así que no hay `token_set_ratio` y el nombre suma 0. Fuera del
  set, lo mismo pasa con la clave de GDELT `CRESY`.
- **A059, Banco Galicia (clave de GDELT)**, que queda en revisión (60 puntos) en vez de unirse a Banco
  de Galicia y Buenos Aires. Causa: sin el país supuesto le faltan los 10 puntos.

Posibles ajustes (sin aplicar): permitir `token_set_ratio` con un solo token si es poco frecuente en el
universo (CRESUD sí, UTE no), y darle a las claves de GDELT el país del registro con el que comparten CIK.

## Integridad después de aplicar la v2 al job
Corrida de la tarea `resolucion` con el código v2, más `dbt build` de Gold (24/24): 1268 registros
únicos, 1137 entidades = 1137 golden records, ninguno sin nombre. Ninguna entidad con dos LEI firmes
ni dos CIK (sin contar Wikidata). Ningún par determinístico separado ni vetado junto. Los 11 aceptados
que quedaron separados son los 11 conflictos de `resolution.revision`, más 51 casos a revisar.
