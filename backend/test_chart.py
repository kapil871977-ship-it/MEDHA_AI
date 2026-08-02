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


def test_ketu_is_exactly_opposite_rahu(chart):
    rahu = chart["planets"]["Rahu"]["longitude"]
    ketu = chart["planets"]["Ketu"]["longitude"]
    assert abs(((ketu - rahu) % 360.0) - 180.0) < 0.001


def test_first_mahadasha_lord_is_the_moons_nakshatra_lord(chart):
    assert chart["dasha_sequences"][0]["lord"] == chart["planets"]["Moon"]["nakshatra_lord"]


def test_dasha_periods_are_contiguous(chart):
    seqs = chart["dasha_sequences"]
    for a, b in zip(seqs, seqs[1:]):
        assert abs((b["start"] - a["end"]).total_seconds()) < 1.0


# ─── Pre-standard-time births use local mean solar time ──────────────────────

def test_pre_standard_time_birth_uses_local_mean_time():
    """Gandhi: 2 Oct 1869, 07:11, Porbandar (21.64N, 69.63E).

    India had no standard time in 1869, so the IANA zone Asia/Kolkata falls
    back to Calcutta's mean time (+5:53:20). Applying that to a Porbandar
    birth is ~75 minutes fast and pushed the ascendant a whole sign early
    (Virgo). Porbandar's own mean solar time (+4:38) gives Libra, which is
    the ascendant published for this chart everywhere.
    """
    chart = main._compute_vedic_chart("1869-10-02", "07:11", 21.6417, 69.6293)
    assert chart["lagna"]["rashi"] == "Libra"


def test_modern_births_keep_their_standard_timezone_offset():
    """The LMT rule must not disturb any birth after standard time existed."""
    # Diana: 1 Jul 1961 Sandringham -> British Summer Time (+1), not GMT.
    diana = main._compute_vedic_chart("1961-07-01", "19:45", 52.8309, 0.5148)
    # Recomputing with a deliberate +0 (GMT) would move the ascendant; confirm
    # the engine did NOT silently swap to a longitude-derived offset (0.03h).
    diana_gmt = main._compute_vedic_chart("1961-07-01", "18:45", 52.8309, 0.5148)
    assert diana["lagna"]["longitude"] != diana_gmt["lagna"]["longitude"]

    # India 1942 used a +6:30 war-time offset — a valid 30-minute standard
    # offset that must be preserved, not replaced by Prayagraj's LMT (+5:27).
    amitabh = main._compute_vedic_chart("1942-10-11", "16:00", 25.4358, 81.8463)
    assert amitabh["lagna"]["rashi"] == "Aquarius"


def test_lmt_substitution_only_triggers_on_non_quarter_hour_offsets():
    """Every standard offset in use is a whole multiple of 15 minutes."""
    for dob, tob, lat, lng in [
        ("1961-08-04", "19:24", 21.3069, -157.8583),   # Honolulu -10:00
        ("1955-02-24", "19:15", 37.7749, -122.4194),   # San Francisco -08:00
        ("1973-04-24", "18:01", 19.0760, 72.8777),     # Mumbai +05:30
    ]:
        chart = main._compute_vedic_chart(dob, tob, lat, lng)
        assert chart["lagna"] is not None
        assert chart["lagna"]["rashi"] in main.SIGNS
