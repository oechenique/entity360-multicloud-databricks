"""Silver incremental: qué procesa cada corrida y cómo combina lo nuevo con lo que Silver ya tiene.

Python puro: silver.py aplica estas mismas reglas en Spark (joins y MERGE) y los tests las prueban
locales, incluida la equivalencia con el recálculo completo que hacía Silver antes (2026-09-29).

- **Qué es nuevo:** un lote de Bronze (su sha256) se procesa una sola vez. silver._lotes_procesados
  guarda los ya procesados por fuente; una fuente sin lotes pendientes no se toca. Tabla vacía =
  reproceso completo (así migra la primera corrida, y así se fuerza uno a mano).
- **Capa 3 (última extracción por clave):** el registro de un lote nuevo reemplaza al de Silver solo
  si no es más viejo según el orden de su fuente (`gana`). Es el mismo orden que usaba el recálculo
  completo con row_number: orden descendente con nulos al final y, a igual orden, gana el último
  ingerido, que siempre es el lote nuevo.
- **Tablas hijas** (nombres de cada emisor, entidad o ítem): se reemplazan enteras para los padres
  cuyo registro ganó (`delta_hijos`); las de los demás padres no se tocan.
- **SCD2 de GLEIF:** scd2.aplicar ya es incremental (aplica los cambios nuevos sobre la última versión
  e ignora los LSN ya aplicados): solo cambia de dónde salen los cambios, los lotes nuevos.
"""


def pendientes(lotes_en_bronze: set[str], procesados: set[str]) -> set[str]:
    """sha256 de los lotes de Bronze que Silver todavía no procesó."""
    return lotes_en_bronze - procesados


def gana(nuevo, actual) -> bool:
    """¿El registro nuevo reemplaza al de Silver? `nuevo` y `actual` son el valor de orden de la fuente
    (extraído, último cambio, lote) o None. Nulos al final: un orden conocido le gana a uno nulo; a igual
    orden (o los dos nulos) gana el nuevo, que es el último ingerido."""
    if actual is None:
        return True
    if nuevo is None:
        return False
    return nuevo >= actual


def delta_hijos(nuevos: set[tuple], actuales: set[tuple]) -> tuple[set[tuple], set[tuple]]:
    """Para un padre que ganó: (filas a insertar o actualizar, filas a borrar) de su tabla hija."""
    return nuevos, actuales - nuevos
