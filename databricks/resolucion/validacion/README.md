# Set de validación curado a mano (D11)

La calidad de la resolución de identidades se mide contra decisiones humanas, con la evidencia de
cada una. Wikidata y el ticker son señales del matching, no verdad de referencia (D11).

Son unas 120 decisiones en dos tandas:

| Parte | Qué mide | Archivo | Unidad |
|---|---|---|---|
| **A** | Recall (y el del blocking) | `parte_a.csv` | Un **registro** que necesita matching difuso: ¿cuál es su LEI en el legacy, si tiene? |
| **B** | Precisión en los casos difíciles | `parte_b.csv` (se genera después de la parte A) | Un **par** de registros: ¿son la misma entidad? |

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

## Regenerar

```powershell
.venv\Scripts\python.exe -m pip install -r databricks\requirements-local.txt
.venv\Scripts\python.exe databricks\resolucion\validacion\generar_parte_a.py
```

El script **pisa** `parte_a.csv`: no regenerarlo después de empezar a etiquetar.

## Fuentes y licencias
Nombres e identificadores de registros públicos: GLEIF (CC0), SEC EDGAR (dominio público),
Wikidata (CC0), OpenSanctions (CC BY-NC 4.0, uso no comercial, con atribución: "Datos:
OpenSanctions (opensanctions.org), CC BY-NC 4.0") y GDELT (con cita y enlace a
https://www.gdeltproject.org/).
