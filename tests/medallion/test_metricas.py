"""Intervalo de Wilson al 95 % y precisión/recall (D11)."""

import pytest

import metricas


@pytest.mark.parametrize("x,n,lo,hi", [
    # Valores de referencia (Wilson score interval, z = 1,96)
    (8, 10, 0.4902, 0.9433),
    (50, 50, 0.9287, 1.0),
    (0, 20, 0.0, 0.1611),
    (45, 60, 0.6277, 0.8422),                   # calculado a mano: centro 0,7350 ± 0,1073
])
def test_wilson(x, n, lo, hi):
    a, b = metricas.wilson(x, n)
    assert (round(a, 4), round(b, 4)) == (lo, hi)


def test_wilson_sin_casos():
    assert metricas.wilson(0, 0) == (0.0, 1.0)


def test_precision_recall():
    r = metricas.precision_recall({("sec:1", "lei:A"), ("sec:2", "lei:B"), ("os:9", "lei:Z")},
                                  {("sec:1", "lei:A"), ("sec:2", "lei:B"), ("wd:5", "lei:C")})
    assert (r["vp"], r["fp"], r["fn"]) == (2, 1, 1)
    assert r["precision"] == pytest.approx(2 / 3) and r["recall"] == pytest.approx(2 / 3)
    assert r["precision_ic95"][0] < 2 / 3 < r["precision_ic95"][1]
