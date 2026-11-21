import math

import pytest

import colormap

def _raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False

STOPS = [(0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))]


def _c():
    return colormap.ColorMap(STOPS, 256)


def _check_zero():
    return _c().lookup(0.0) == (0.0, 0.0, 0.0)


def _check_one():
    return _c().lookup(1.0) == (1.0, 1.0, 1.0)


def _check_mid():
    return abs(_c().lookup(0.5)[0] - 0.5) < 0.01


def _check_hi():
    return _c().lookup(2.0) == (1.0, 1.0, 1.0)


def _check_lo():
    return _c().lookup(-1.0) == (0.0, 0.0, 0.0)


def _check_valid():
    return _c().validate() is True


def _check_bad_mono():
    bad = [(0.0, (1.0, 0.0, 0.0)), (1.0, (0.0, 0.0, 0.0))]
    return _raises(lambda: colormap.ColorMap(bad, 16).validate())


def _check_bad_levels():
    return _raises(lambda: colormap.ColorMap(STOPS, 0))


def _check_empty():
    return _raises(lambda: colormap.ColorMap([], 16))


def _check_type():
    return isinstance(_c().lookup(0.3), tuple)


def _check_range():
    return all(0.0 <= v <= 1.0 for v in _c().lookup(0.7))


def _check_det():
    return _c().lookup(0.4) == _c().lookup(0.4)


def _check_three():
    c = colormap.ColorMap([(0.0, (0.0, 0.0, 0.0)), (0.5, (1.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))], 64)
    return abs(c.lookup(0.25)[0] - 0.5) < 0.05


def _check_nomut():
    src = list(STOPS)
    _c().lookup(0.5)
    return STOPS == src


def _check_float():
    return isinstance(_c().lookup(0.1)[0], float)

CASES = [("zero", "_check_zero"), ("one", "_check_one"), ("mid", "_check_mid"), ("hi", "_check_hi"), ("lo", "_check_lo"), ("valid", "_check_valid"), ("bad_mono", "_check_bad_mono"), ("bad_levels", "_check_bad_levels"), ("empty", "_check_empty"), ("type", "_check_type"), ("range", "_check_range"), ("det", "_check_det"), ("three", "_check_three"), ("nomut", "_check_nomut"), ("float", "_check_float")]


@pytest.mark.parametrize("name,check", CASES, ids=[c[0] for c in CASES])
def test_spec(name, check):
    assert globals()[check]() is True
