# Set de validación curado a mano (D11)

La calidad de la resolución de identidades se mide contra decisiones humanas, con la evidencia de
cada una. Wikidata y el ticker son señales del matching, no verdad de referencia (D11).

Son unas 120 decisiones en dos tandas:

| Parte | Qué mide | Archivo | Unidad |
|---|---|---|---|
| **A** | Recall (y el del blocking) | `parte_a.csv` | Un **registro** que necesita matching difuso: ¿cuál es su LEI en el legacy, si tiene? |
| **B** | Precisión en los pares que la parte A no decide | `parte_b.csv` (sale de la primera corrida de la resolución) | Un **par** de registros: ¿son la misma entidad? |

**Quién etiquetó:** las dos partes las etiquetó el autor del proyecto (Gastón), en una sesión
(2026-09-27), con una línea de evidencia por decisión. Es un solo anotador y una sola pasada: no hay
acuerdo entre anotadores que medir, y la evidencia breve permite auditar cada decisión.

Precisión y recall se publican con **intervalo de Wilson al 95 %** (`databricks/medallion/metricas.py`).
Los pesos y umbrales se calibran con la mitad de las decisiones (partición por estrato, semilla fija) y
las métricas se informan sobre la otra mitad.

## Parte A: cómo etiquetar

`parte_a.csv` se abre en Excel: está separado por `;` y en UTF-8 con BOM.

- **Cada fila es un registro de una fuente** (SEC EDGAR, OpenSanctions, Wikidata o GDELT) sin LEI
  propio, con hasta 5 candidatos del legacy (`c1_…` a `c5_…`). Los candidatos están **en orden
  aleatorio** y sin puntaje, a propósito, para no anclar la decisión.
- Completar:
  - `respuesta`:
    - `1` a `5`: el candidato que es la misma entidad legal.
    - `ninguno`: la entidad no está en el legacy.
    - `otro`: está, pero no entre los candidatos; poner el LEI en `lei_otro`. Buscarlo con el
      link de `buscar_en_gleif`.
    - `incierto`: no se puede decidir con la evidencia disponible. Queda fuera de las métricas y se
      informa aparte.
  - `evidencia` (**obligatoria**): por qué, en una línea. Por ejemplo: "mismo CUIT en el 20-F",
    "la SEC lista el nombre anterior Macro Bansud", "es la matriz, no el banco" o "sancionada
    cubana sin registro en AR".
  - `fecha`: día de la decisión.
- **Misma entidad legal**, no el mismo grupo: la matriz y la filial son entidades distintas, y la
  sucursal argentina de una empresa extranjera también.
- Si hay dos LEI de la misma entidad (duplicado en GLEIF), elegir el que está `ISSUED` y anotarlo
  en `evidencia`.

## Parte B: cómo etiquetar

**Etiquetar la parte B después de terminar la parte A**: la parte B muestra pares que la resolución
juntó, y verlos antes puede anclar las respuestas de la parte A.

- Cada fila es un **par** de registros (`a_…` y `b_…`) que la primera corrida de la resolución (pesos
  sin calibrar) comparó. Sin puntaje y en orden aleatorio, como en la parte A.
- No están los pares de un registro de la parte A contra GLEIF, ni los de un registro ligado a uno
  de la parte A por un CIK o un LEI compartido (por ejemplo, la clave de GDELT de un emisor de la
  SEC): esos los decide la respuesta de la parte A. Están los duplicados dentro de GLEIF (un LEI
  anulado contra uno vigente) y los pares entre fuentes que la parte A no cubre.
- **Casi no hay positivos difíciles** (misma entidad con nombres muy distintos: 1 en la primera
  corrida). Esos casos son los registros de fuentes externas contra el legacy, que cubre la parte A:
  **su recall se mide en la parte A**, no en la B.
- Completar `respuesta` (`match`, `no_match` o `incierto`), `evidencia` (**obligatoria**) y `fecha`, con el
  mismo criterio de **misma entidad legal** de la parte A.
- `parte_b_estratos.csv` tiene el estrato de cada par (dudoso, positivo difícil, negativo difícil,
  fácil), que se usa para partir el set en calibración y evaluación. **No abrirlo antes de terminar.**

## Regenerar

```powershell
.venv\Scripts\python.exe -m pip install -r databricks\requirements-local.txt
.venv\Scripts\python.exe databricks\resolucion\validacion\generar_parte_a.py
```

```powershell
.venv\Scripts\python.exe databricks\resolucion\validacion\generar_parte_b.py
```

Los scripts **pisan** `parte_a.csv` y `parte_b.csv`: no regenerarlos después de empezar a etiquetar.

## Fuentes y licencias
Nombres e identificadores de registros públicos: GLEIF (CC0), SEC EDGAR (dominio público),
Wikidata (CC0), OpenSanctions (CC BY-NC 4.0, uso no comercial, con atribución: "Datos:
OpenSanctions (opensanctions.org), CC BY-NC 4.0") y GDELT (con cita y enlace a
https://www.gdeltproject.org/).
