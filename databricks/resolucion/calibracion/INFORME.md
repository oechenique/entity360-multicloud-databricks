# Calibración y evaluación de la resolución de identidades (2026-09-27)

Set curado a mano (D11): parte A (59 registros) + parte B (60 pares), sin `incierto`. Partición por
estrato (A: fuente; B: estrato del generador), semilla 20260927: **62 unidades de calibración y 57 de
evaluación**. Script: `calibrar.py` (usa `identidades.senales`/`decidir`, el mismo código del job);
números completos: `resultados_v1.json` y `resultados_v2.json`.

| Versión | Qué es | ¿Evaluación ciega? |
|---|---|---|
| **v1** | Resolución inicial (commit `df09b07`) | **Sí**: nadie miró los errores antes de medir |
| **v2** | v1 + las 4 correcciones de abajo, con los mismos pesos | **No**: las correcciones salieron de mirar los errores de todo el set, incluida la mitad de evaluación |
| **v2.1** | v2 + los 2 ajustes de la sección "v2.1" (token único raro por idf, país heredado en GDELT) | **No**: los ajustes y el umbral de idf salieron de mirar el set completo |

## Resultados (Wilson 95 %)

**Mitad de evaluación (57 unidades):**

| | Precisión | Recall | VP / FP / FN |
|---|---|---|---|
| **v1 (ciega)** | **0,913** [0,732–0,976] | **0,955** [0,782–0,992] | 21 / 2 / 1 |
| v2 (no ciega) | 1,000 [0,851–1,000] | 1,000 [0,851–1,000] | 22 / 0 / 0 |
| v2.1 (no ciega) | 1,000 [0,851–1,000] | 1,000 [0,851–1,000] | 22 / 0 / 0 |

**Set completo (119 unidades; la mitad de calibración también la vio el diagnóstico):**

| | VP / FP / FN | Precisión | Recall |
|---|---|---|---|
| v1 | 43 / 4 / 3 | 0,915 | 0,935 |
| v2 | 44 / 0 / 2 | 1,000 | 0,957 |
| v2.1 | 45 / 0 / 1 | 1,000 | 0,978 |

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

## v2.1 (2026-09-29): los dos ajustes
Resultados completos en `resultados_v2.1.json`. Mismos pesos y umbral (70), misma partición.

| Ajuste | Regla | Test |
|---|---|---|
| **Token único raro** | `token_set_ratio` también se usa si un nombre es **un solo token significativo con idf ≥ 5,7** en el universo: idf = ln(N / df), N = registros de la resolución, df = registros que tienen el token (`identidades.IDF_MIN_TOKEN_UNICO`). Los tokens genéricos (UTE, joint venture, consorcio) nunca cuentan. | `test_v21_token_unico_raro_une_cresud`, `test_v21_token_unico_frecuente_no_usa_token_set`, `test_v21_genericos_nunca_son_raros` |
| **País heredado en GDELT** | Una clave de GDELT sin país hereda los países de los registros de SEC, GLEIF firme u OpenSanctions con los que comparte CIK o LEI (`identidades.heredar_paises`). Wikidata no presta país (es señal). Sin identificador compartido, la clave queda sin país: nunca se supone uno. | `test_v21_gdelt_hereda_pais_del_cik`, `test_v21_gdelt_hereda_pais_real_no_supuesto`, `test_v21_wikidata_no_presta_pais`, `test_v21_banco_galicia_sin_identificador_queda_en_revision` |

**Cómo se eligió el umbral de idf.** Con N = 1268, los nombres de un solo token tienen df entre 1 y 6
(CRESUD: df 3, idf 6,05; GLOBANT: df 5, idf 5,54; SIEMENS e YPF: df 6, idf 5,35). Se corrió la
resolución completa con umbrales de 4,5 a 7,0:

| Umbral de idf | Entidades | Set completo VP/FP/FN | Errores del set |
|---|---|---|---|
| sin token único (v2 + herencia) | 1137 | 44 / 0 / 2 | A006, A059 |
| 6,4 – 7,0 | 1137 | 44 / 0 / 2 | A006, A059 |
| **5,7 – 6,0** | **1136** | **45 / 0 / 1** | **A059** |
| 4,5 – 5,5 | 1138 | 43 / 0 / 3 | A013, A054, A059 |

Todo umbral en (5,54; 6,05] da exactamente los mismos clusters. En 5,54 entra GLOBANT: la clave de
GDELT `GLOB` empata en 100 con más de una Globant de GLEIF y el empate manda los pares a revisión (A013 y
A054 se pierden). Se fija **5,7**, que admite df ≤ 4: CRESUD entra con un registro de margen y GLOBANT
queda afuera con 0,16 de margen. Si el universo crece, N sube y el mismo df da más idf: el umbral se
revisa cuando cambie el universo (fase opcional).

**Resultado de los casos de la v2:**
- **A006 (Cresud) — recuperado.** "CRESUD INC" (SEC) contra "Cresud S.A. Comercial Industrial
  Financiera y Agropecuaria" (GLEIF): similitud 100, 75 puntos, aceptado. La clave `CRESY` hereda AR de la
  SEC y queda en la misma entidad.
- **A059 (Banco Galicia) — sigue en revisión, a propósito.** La clave `BANCO_GALICIA` del diccionario
  no trae CIK ni LEI (es la subsidiaria de GGAL, que no presenta ante la SEC), así que no comparte
  identificador con nadie y no hereda país. Queda con 60 puntos (nombre 60, sin país) en
  `resolution.revision`. Unirla exigiría suponer AR, que es justo lo que la v2 sacó. La grilla de la v2.1
  vuelve a proponer bajar el umbral a 60 (lo resolvería sin empeorar la evaluación), pero eso aceptaría
  también todos los pares que hoy están en 60 a revisar: **se deja 70**.

**Ninguno de los 7 errores de la v1 reaparece** (A016, A058, A028, B019, B037, B045, B038): la lista de
unidades con error de la v2.1 es solo A059 (`errores_con_iniciales` en el JSON).

**Efecto fuera del set.** Los clusters cambian solo en Cresud (1137 → 1136 entidades). La herencia sí
mueve puntajes: 16 de las 17 claves de GDELT heredan país de la SEC por su CIK (13 AR; VIST hereda MX y
deja de acercarse a la filial argentina; MELI hereda UY; GLOB, ES y LU); solo `BANCO_GALICIA` queda sin
país. Muchos pares de GDELT que estaban en 60 (revisar) pasan a 70
dentro de la entidad a la que ya estaban unidos por CIK, o a 40 si el país no coincide; los que llegan a
70 contra varias filiales (BBVA Argentina contra BBVA Asset Management y BBVA Francés Valores) empatan y
van a revisión como empates. Pares puntuados: 4912 (el país heredado agrega bloques de país y prefijo).

## Integridad después de aplicar la v2 al job
Corrida de la tarea `resolucion` con el código v2, más `dbt build` de Gold (24/24): 1268 registros
únicos, 1137 entidades = 1137 golden records, ninguno sin nombre. Ninguna entidad con dos LEI firmes
ni dos CIK (sin contar Wikidata). Ningún par determinístico separado ni vetado junto. Los 11 aceptados
que quedaron separados son los 11 conflictos de `resolution.revision`, más 51 casos a revisar.

## Integridad después de aplicar la v2.1 al job (2026-09-29)
Corrida parcial del job `entity360-medallion` (solo la tarea `resolucion`, 2,7 min, SUCCESS) con el
código v2.1, chequeos de `databricks/resolucion/integridad.py` (7/7 OK) y `dbt build` de Gold (24/24):

| | v2 | v2.1 |
|---|---|---|
| Registros | 1268 | 1268 |
| Pares puntuados | 4699 | 4912 |
| Decisiones | — | rechazado 4579, aceptado 159, veto 120, determinístico 34, revisar 20 |
| Entidades = golden records | 1137 | 1136 (98 con más de un registro) |
| `resolution.revision` | 11 conflictos + 51 revisar | 11 conflictos + 8 empates + 20 revisar |

Ninguna entidad con dos LEI firmes ni dos CIK (sin contar Wikidata); ningún par determinístico
separado sin conflicto; ningún par vetado junto; todo aceptado que quedó separado es un conflicto o un
empate de `resolution.revision`. La calibración, corrida de nuevo sobre la tabla que escribió el job,
da los mismos números que la reconstrucción local (1136 entidades, solo A059 con error).
