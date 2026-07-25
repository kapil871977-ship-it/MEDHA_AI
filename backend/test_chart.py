"""
Tests for MEDHA AI's core Vedic-chart computation.

These exercise the pure ephemeris functions (no API keys / no network needed):
  - _compute_vedic_chart
  - _build_computed_houses

Run from the backend/ directory:
    pytest
"""
import importlib

import pytest

main = importlib.import_module("main")

# A fixed birth: 17 Jul 1995, 14:30, New Delhi (28.6139 N, 77.2090 E)
DOB, TOB, LAT, LNG = "1995-07-17", "14:30", 28.6139, 77.2090

EXPECTED_PLANETS = {
    "Sun", "Moon", "Mars", "Mercury", "Jupiter",
    "Venus", "Saturn", "Rahu", "Ketu",
}


@pytest.fixture(scope="module")
def chart():
    return main._compute_vedic_chart(DOB, TOB, LAT, LNG)


def test_chart_has_expected_top_level_keys(chart):
    for key in ("lagna", "planets", "planet_houses", "dasha",
                "dasha_sequences", "ayanamsa"):
        assert key in chart, f"chart missing '{key}'"


def test_lagna_is_a_valid_sign(chart):
    lagna = chart["lagna"]
    assert lagna["rashi"] in main.SIGNS
    assert isinstance(lagna["longitude"], (int, float))


def test_all_nine_grahas_present(chart):
    assert set(chart["planets"].keys()) == EXPECTED_PLANETS


def test_planet_longitudes_in_range(chart):
    for name, p in chart["planets"].items():
        lon = p["longitude"]
        assert 0.0 <= lon < 360.0, f"{name} longitude {lon} out of range"
        assert p["rashi"] in main.SIGNS


def test_ayanamsa_is_lahiri_ballpark(chart):
    # Lahiri ayanamsa for the late 1990s is ~23.8 degrees.
    assert 23.0 < chart["ayanamsa"] < 25.0


def test_dasha_resolved(chart):
    # A valid birth date should resolve a current mahadasha lord.
    assert chart["dasha"].get("mahadasha") not in (None, "", "Unknown")


def test_build_computed_houses_returns_twelve(chart):
    houses = main._build_computed_houses(chart, "hi")
    assert len(houses) == 12
    assert [h["house"] for h in houses] == list(range(1, 13))


def test_each_house_has_required_fields(chart):
    houses = main._build_computed_houses(chart, "hi")
    for h in houses:
        assert h["sign"] in main.SIGNS
        assert h["lord"]                      # non-empty lord
        assert isinstance(h["occupants"], list)
        assert isinstance(h["analysis"], str) and h["analysis"]
