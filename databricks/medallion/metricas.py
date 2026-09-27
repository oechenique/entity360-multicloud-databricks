"""Precisión y recall del matching contra el set de validación curado a mano (D11), con
intervalo de confianza de Wilson al 95 %.

Wilson y no el intervalo normal (Wald): con pocos casos y proporciones cerca de 1, Wald se sale de
[0, 1] y subestima la incertidumbre. El set tiene ~120 decisiones: los intervalos van a ser anchos,
y el README los publica así.
"""

from math import sqrt

Z95 = 1.959963984540054


def wilson(exitos: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = exitos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def precision_recall(predichos: set, verdaderos: set) -> dict:
    """predichos: pares que el matching aceptó; verdaderos: pares etiquetados como match.
    Los pares etiquetados `incierto` no entran a ninguno de los dos conjuntos."""
    vp = len(predichos & verdaderos)
    return {
        "vp": vp, "fp": len(predichos - verdaderos), "fn": len(verdaderos - predichos),
        "precision": vp / len(predichos) if predichos else None,
        "precision_ic95": wilson(vp, len(predichos)),
        "recall": vp / len(verdaderos) if verdaderos else None,
        "recall_ic95": wilson(vp, len(verdaderos)),
    }
