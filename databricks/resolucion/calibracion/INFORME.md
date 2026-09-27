# Calibración de la resolución de identidades (2026-09-27)

Set curado a mano (D11): parte A (59 registros) + parte B (60 pares), sin `incierto`. Partición por
estrato (A: fuente; B: estrato del generador), semilla 20260927: **62 unidades de calibración y 57 de
evaluación**. Script: `calibrar.py`; números completos: `resultados.json`. La reconstrucción local da lo
mismo que el job (1268 registros, 5011 pares, 1132 entidades, 0 diferencias de puntaje).

## Resultado: la grilla no cambia los pesos
Grilla de 14.580 combinaciones (peso del nombre y su piso, país, ticker/dominio, fondo, números, umbral
de aceptación). **6.561 empatan en el máximo F1 de calibración (0,917), y los pesos iniciales están
entre ellas**: el desempate (lo más cerca de los iniciales) los deja iguales. Ningún peso corrige los
errores que quedan (ver abajo): son estructurales.

## Métricas sobre la mitad de evaluación (pesos iniciales = calibrados), Wilson 95 %

| | Precisión | Recall | VP / FP / FN |
|---|---|---|---|
| **A + B** | **0,913** [0,732–0,976] | **0,955** [0,782–0,992] | 21 / 2 / 1 |
| Parte A (registro → legacy) | 0,846 [0,578–0,957] | 1,000 [0,741–1,000] | 11 / 2 / 0 |
| Parte B (pares) | 1,000 [0,722–1,000] | 0,909 [0,623–0,984] | 10 / 0 / 1 |

**Recall del blocking** (parte A, el LEI correcto es candidato del registro): 11/11 en evaluación
[0,741–1,000]; 22/22 en todo el set [0,851–1,000]. Directo y por conexión en el grafo de candidatos dan
lo mismo.

Los intervalos son anchos: 57 unidades de evaluación. Es lo que se publica.

## Errores que quedan (todo el set, pesos iniciales) y su causa

| Unidad | Error | Causa |
|---|---|---|
| A016 [cal], A058 [ev] | Vista Energy S.A.B. de C.V. (matriz mexicana) y Vista Oil & Gas unidos a Vista Energy Argentina S.A.U. (filial) | La clave de GDELT `VIST` se une a la filial por nombre con 70 puntos (justo el umbral) **porque `resolucion.py` le asigna país AR** a todas las claves de GDELT; y por CIK arrastra a la matriz. Sin ese país supuesto serían 60. |
| A028 [ev] | Constructora J.C. Segura unida a Casino Buenos Aires S.A. (una UTE) | OpenSanctions trae alias genéricos (`Ute`, `The Joint Venture`). `token_set_ratio` da 100 cuando un nombre es subconjunto del otro, y "UTE" está en el nombre de la UTE del casino. |
| B019, B045 [cal], B037 [ev] | BCRA, ICBC y Banco Provincia del Neuquén: el LEI anulado y el vigente no se unen | El anulado empata en 75 puntos con su gemelo y con otra entidad; el empate se resuelve por orden de clave y se une primero a la otra. Después la restricción (un LEI firme por cluster) bloquea al gemelo. **Además son uniones falsas que el set no mide:** el BCRA anulado quedó con "República Argentina" (el Estado), el de Neuquén con "Provincia de Neuquén" y el de ICBC con Banco Industrial S.A. Los gemelos comparten los primeros 17 caracteres del LEI y la fecha de alta (reemisión de la LOU argentina, 2015). |
| B038 [cal] | Cablevisión Holding y Flow unidos | Vínculo determinístico por LEI: el ítem de Wikidata de Flow (una marca comercial) trae el LEI de Cablevisión Holding. Es el caso que el D11 anticipa: Wikidata es señal, no verdad. |

## Advertencia sobre la mitad de evaluación
Este diagnóstico miró los errores de **todo** el set, incluida la mitad de evaluación. Si se corrigen
estas causas, las métricas de evaluación dejan de ser ciegas para esos cambios. Opciones: publicarlo
así, aclarado, o etiquetar una tanda nueva chica para evaluar después de los cambios.
