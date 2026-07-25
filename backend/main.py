import os
import json
import re
import asyncio
import sqlite3
import hmac
import hashlib
import base64
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List
from dotenv import load_dotenv
import google.generativeai as genai
try:
    from openai import OpenAI as _OpenAIClient
except ImportError:
    _OpenAIClient = None
from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import concurrent.futures
import logging
logging.basicConfig(level=logging.INFO)
import swisseph as swe
from timezonefinder import TimezoneFinder
import httpx

# â”€â”€â”€ Vedic Astrology Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]
SIGNS_HI = [
    "Mesh","Vrishabh","Mithun","Kark","Singh","Kanya",
    "Tula","Vrishchik","Dhanu","Makar","Kumbh","Meen"
]
SIGN_LORDS = {
    "Aries":"Mars","Taurus":"Venus","Gemini":"Mercury","Cancer":"Moon",
    "Leo":"Sun","Virgo":"Mercury","Libra":"Venus","Scorpio":"Mars",
    "Sagittarius":"Jupiter","Capricorn":"Saturn","Aquarius":"Saturn","Pisces":"Jupiter"
}
NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra",
    "Punarvasu","Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni",
    "Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha",
    "Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishtha",
    "Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"
]
NAKSHATRA_LORDS = [
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury",
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury",
    "Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"
]
DASHA_YEARS = {
    "Ketu":7,"Venus":20,"Sun":6,"Moon":10,"Mars":7,
    "Rahu":18,"Jupiter":16,"Saturn":19,"Mercury":17
}
DASHA_ORDER = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]

EXALTED_IN = {
    "Sun":"Aries","Moon":"Taurus","Mars":"Capricorn","Mercury":"Virgo",
    "Jupiter":"Cancer","Venus":"Pisces","Saturn":"Libra"
}
DEBILITATED_IN = {
    "Sun":"Libra","Moon":"Scorpio","Mars":"Cancer","Mercury":"Pisces",
    "Jupiter":"Capricorn","Venus":"Virgo","Saturn":"Aries"
}
OWN_SIGNS = {
    "Sun":["Leo"],"Moon":["Cancer"],"Mars":["Aries","Scorpio"],
    "Mercury":["Gemini","Virgo"],"Jupiter":["Sagittarius","Pisces"],
    "Venus":["Taurus","Libra"],"Saturn":["Capricorn","Aquarius"]
}

NAK_SPAN = 360.0 / 27.0  # ~13.333 degrees per nakshatra

SYSTEM_WEIGHTS = {
    "parashar": 0.5,
    "kp": 0.3,
    "jaimini": 0.1,
    "bhrigu": 0.1,
}

ASTRO_RULEBOOK = {
    "global_rules": [
        {"id": "G1", "condition": "lagna_lord_strong", "result": "overall_positive", "weight": 0.6, "system": "parashar"},
        {"id": "G2", "condition": "lagna_lord_afflicted", "result": "overall_instability", "weight": -0.6, "system": "parashar"},
        {"id": "G3", "condition": "benefics_in_kendra", "result": "supportive_life", "weight": 0.5, "system": "parashar"},
        {"id": "G4", "condition": "malefics_in_kendra", "result": "struggle", "weight": -0.5, "system": "parashar"},
    ],
    "marriage_rules": [
        {"id": "M1", "condition": "strong_7th_lord AND benefic_aspect_7th", "result": "marriage_positive", "weight": 0.8, "system": "parashar"},
        {"id": "M2", "condition": "lord7_in_6_8_12", "result": "marriage_delay_or_issue", "weight": -0.7, "system": "parashar"},
        {"id": "M3", "condition": "venus_strong", "result": "relationship_harmony", "weight": 0.6, "system": "parashar"},
        {"id": "M4", "condition": "venus_afflicted OR rahu_in_7th", "result": "relationship_instability", "weight": -0.8, "system": "bhrigu"},
        {"id": "M5", "condition": "kp_7th_sublord_connected_2_7_11", "result": "marriage_yes", "weight": 0.9, "system": "kp"},
    ],
    "career_rules": [
        {"id": "C1", "condition": "strong_10th_lord", "result": "career_success", "weight": 0.8, "system": "parashar"},
        {"id": "C2", "condition": "saturn_in_10th", "result": "slow_but_stable_career", "weight": 0.5, "system": "parashar"},
        {"id": "C3", "condition": "lord10_in_6th", "result": "job_service", "weight": 0.6, "system": "parashar"},
        {"id": "C4", "condition": "lord10_in_7th", "result": "business", "weight": 0.6, "system": "parashar"},
        {"id": "C5", "condition": "kp_10th_sublord_connected_2_6_10_11", "result": "career_event_yes", "weight": 0.9, "system": "kp"},
    ],
    "wealth_rules": [
        {"id": "W1", "condition": "lords2_11_strong", "result": "wealth_gain", "weight": 0.8, "system": "parashar"},
        {"id": "W2", "condition": "jupiter_in_2_or_11", "result": "financial_growth", "weight": 0.7, "system": "parashar"},
        {"id": "W3", "condition": "lord2_afflicted", "result": "financial_instability", "weight": -0.7, "system": "parashar"},
        {"id": "W4", "condition": "rahu_in_11th", "result": "sudden_gain", "weight": 0.6, "system": "bhrigu"},
    ],
    "health_rules": [
        {"id": "H1", "condition": "house6_afflicted", "result": "disease_risk", "weight": -0.7, "system": "parashar"},
        {"id": "H2", "condition": "lagna_lord_strong AND benefic_in_6th", "result": "disease_resistance", "weight": 0.6, "system": "parashar"},
        {"id": "H3", "condition": "saturn_rahu_in_6_or_8", "result": "chronic_disease", "weight": -0.8, "system": "bhrigu"},
    ],
    "market_rules": [
        {"id": "T1", "condition": "jupiter_transit_2_5_9_11", "result": "market_bullish", "weight": 0.7, "system": "parashar"},
        {"id": "T2", "condition": "saturn_transit_8_12", "result": "market_bearish", "weight": -0.7, "system": "parashar"},
        {"id": "T3", "condition": "rahu_transit_2_5_11", "result": "volatile_market", "weight": 0.6, "system": "jaimini"},
        {"id": "T4", "condition": "moon_afflicted_today", "result": "intraday_volatility", "weight": -0.5, "system": "bhrigu"},
    ],
    "kp_core_rules": [
        {"id": "KP1", "condition": "sublord_connected_2_6_10_11", "result": "event_yes", "weight": 0.9, "system": "kp"},
        {"id": "KP2", "condition": "sublord_connected_6_8_12", "result": "event_no", "weight": -0.9, "system": "kp"},
    ],
    "bhrigu_fast_rules": [
        {"id": "BR1", "condition": "venus_rahu", "result": "relationship_issue", "weight": -0.7, "system": "bhrigu"},
        {"id": "BR2", "condition": "jupiter_moon", "result": "gajakesari_effect", "weight": 0.7, "system": "bhrigu"},
        {"id": "BR3", "condition": "saturn_moon", "result": "mental_stress", "weight": -0.6, "system": "bhrigu"},
    ],
}


def _load_engine_config() -> dict:
    default_cfg = {
        "meta": {"version": "4.0", "modules": ["market_prediction", "market_past", "investment_advice"]},
        "market_prediction": {"future_logic": {}},
        "market_past": {"logic": []},
        "investment_advice": {"commodity_mapping": []},
    }
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "engine_config.json")
        if not os.path.exists(cfg_path):
            return default_cfg
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return raw
    except Exception as cfg_err:
        print("ENGINE CONFIG WARNING:", repr(cfg_err))
    return default_cfg


ENGINE_CONFIG = _load_engine_config()


def _normalize_score(raw_score: float, max_abs_score: float) -> float:
    if max_abs_score <= 0:
        return 0.5
    value = (raw_score + max_abs_score) / (2.0 * max_abs_score)
    return max(0.0, min(1.0, value))


def _eval_condition_expr(expr: str, flags: Dict[str, bool]) -> bool:
    if not expr:
        return False
    normalized = str(expr).replace("AND", " and ").replace("OR", " or ")
    tokens = re.findall(r"and|or|\(|\)|[A-Za-z0-9_]+", normalized)
    if not tokens:
        return False
    safe_parts = []
    for t in tokens:
        if t in {"and", "or", "(", ")"}:
            safe_parts.append(t)
        else:
            safe_parts.append("True" if flags.get(t, False) else "False")
    safe_expr = " ".join(safe_parts)
    try:
        return bool(eval(safe_expr, {"__builtins__": {}}, {}))
    except Exception:
        return False


def _condition_score(rules: List[dict], flags: Dict[str, bool]) -> dict:
    raw = 0.0
    max_abs = 0.0
    hits = []
    system_scores = {"parashar": 0.0, "kp": 0.0, "jaimini": 0.0, "bhrigu": 0.0}
    system_abs = {"parashar": 0.0, "kp": 0.0, "jaimini": 0.0, "bhrigu": 0.0}

    for rule in rules:
        weight = float(rule.get("weight", 0.0))
        system = str(rule.get("system", "parashar"))
        max_abs += abs(weight)
        if system in system_abs:
            system_abs[system] += abs(weight)

        if _eval_condition_expr(str(rule.get("condition", "")), flags):
            raw += weight
            hits.append({
                "id": rule.get("id", ""),
                "result": rule.get("result", ""),
                "weight": weight,
                "system": system,
            })
            if system in system_scores:
                system_scores[system] += weight

    normalized_system_scores = {}
    for system in system_scores.keys():
        normalized_system_scores[system] = _normalize_score(system_scores[system], system_abs[system])

    return {
        "raw": raw,
        "normalized": _normalize_score(raw, max_abs),
        "hits": hits,
        "system_scores": normalized_system_scores,
    }


def _planet_dignity(planet: str, rashi: str) -> str:
    if EXALTED_IN.get(planet) == rashi:
        return "Ucha/Exalted"
    if DEBILITATED_IN.get(planet) == rashi:
        return "Neech/Debilitated"
    if rashi in OWN_SIGNS.get(planet, []):
        return "Swakshetra/Own Sign"
    return ""


def _navamsha_sign_index(rashi_idx: int, degree_in_sign: float) -> int:
    nav_no = min(8, max(0, int((degree_in_sign % 30.0) / (30.0 / 9.0))))
    movable = {0, 3, 6, 9}
    fixed = {1, 4, 7, 10}

    if rashi_idx in movable:
        start_idx = rashi_idx
    elif rashi_idx in fixed:
        start_idx = (rashi_idx + 8) % 12
    else:
        start_idx = (rashi_idx + 4) % 12
    return (start_idx + nav_no) % 12


def _house_lord_for_number(lagna_rashi: str, house_num: int) -> str:
    try:
        lagna_idx = SIGNS.index(lagna_rashi)
    except Exception:
        lagna_idx = 0
    sign_idx = (lagna_idx + int(house_num) - 1) % 12
    return SIGN_LORDS.get(SIGNS[sign_idx], "")


def _planet_lordship_houses(lagna_rashi: str) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for h in range(1, 13):
        lord = _house_lord_for_number(lagna_rashi, h)
        if lord:
            out.setdefault(lord, set()).add(h)
    return out


def _kp_nakshatra_sublord_from_longitude(sidereal_longitude: float) -> dict:
    lon = float(sidereal_longitude) % 360.0
    nak_idx = int(lon / NAK_SPAN)
    nak_lord = NAKSHATRA_LORDS[nak_idx]

    nak_start = nak_idx * NAK_SPAN
    offset = lon - nak_start

    start_idx = DASHA_ORDER.index(nak_lord)
    seq = [DASHA_ORDER[(start_idx + i) % 9] for i in range(9)]

    cum = 0.0
    sublord = seq[-1]
    for lord in seq:
        span = NAK_SPAN * (DASHA_YEARS[lord] / 120.0)
        cum += span
        if offset <= cum:
            sublord = lord
            break

    return {
        "nakshatra": NAKSHATRAS[nak_idx],
        "nakshatra_lord": nak_lord,
        "sublord": sublord,
    }


def _kp_house_sublord_map(chart: dict) -> Dict[int, dict]:
    cusp_lons = chart.get("house_cusps_sidereal", []) or []
    mapping: Dict[int, dict] = {}
    for i, lon in enumerate(cusp_lons[:12], start=1):
        info = _kp_nakshatra_sublord_from_longitude(float(lon))
        mapping[i] = {
            "cusp_longitude": round(float(lon), 4),
            "nakshatra": info["nakshatra"],
            "nakshatra_lord": info["nakshatra_lord"],
            "sublord": info["sublord"],
        }
    return mapping


def _kp_sublord_connected_to_houses(chart: dict, house_num: int, target_houses: set) -> bool:
    kp_map = _kp_house_sublord_map(chart)
    info = kp_map.get(int(house_num))
    if not info:
        return False

    sublord = str(info.get("sublord", "")).strip()
    if not sublord:
        return False

    ph = chart.get("planet_houses", {})
    lagna = chart.get("lagna", {})
    lordships = _planet_lordship_houses(str(lagna.get("rashi", "Aries")))

    placement_house = ph.get(sublord)
    if placement_house in target_houses:
        return True

    if set(lordships.get(sublord, set())).intersection(set(target_houses)):
        return True

    return False


def _kp_sublord_linked_houses(chart: dict, sublord: str) -> List[int]:
    lagna = chart.get("lagna", {})
    ph = chart.get("planet_houses", {})
    lordships = _planet_lordship_houses(str(lagna.get("rashi", "Aries")))
    linked = set()

    placement_house = ph.get(str(sublord or "").strip())
    if placement_house:
        linked.add(int(placement_house))

    for h in lordships.get(str(sublord or "").strip(), set()):
        linked.add(int(h))

    return sorted(linked)


def _kp_full_cusp_table(chart: dict, event_houses: set) -> List[dict]:
    kp_map = _kp_house_sublord_map(chart)
    table = []
    for h in range(1, 13):
        info = kp_map.get(h, {})
        sublord = str(info.get("sublord", "")).strip()
        linked_houses = _kp_sublord_linked_houses(chart, sublord)
        overlap = sorted(set(linked_houses).intersection(set(event_houses)))
        suitability = 0.0
        if linked_houses:
            suitability = len(overlap) / max(1, len(set(event_houses)))

        table.append({
            "house": h,
            "nakshatra": info.get("nakshatra", ""),
            "nakshatra_lord": info.get("nakshatra_lord", ""),
            "sublord": sublord,
            "linked_houses": linked_houses,
            "event_overlap_houses": overlap,
            "event_suitability": round(suitability, 3),
        })

    return table


def _planet_is_strong(planet_name: str, chart: dict) -> bool:
    planets = chart.get("planets", {})
    ph = chart.get("planet_houses", {})
    pdata = planets.get(planet_name, {})
    dignity = str(pdata.get("dignity", ""))
    house = ph.get(planet_name)

    if "Exalted" in dignity or "Own Sign" in dignity:
        return True
    if "Debilitated" in dignity:
        return False
    if house in {1, 4, 5, 7, 9, 10, 11}:
        return True
    return False


def _planet_is_afflicted(planet_name: str, chart: dict) -> bool:
    planets = chart.get("planets", {})
    ph = chart.get("planet_houses", {})
    pdata = planets.get(planet_name, {})
    dignity = str(pdata.get("dignity", ""))
    house = ph.get(planet_name)

    if "Debilitated" in dignity:
        return True
    if house in {6, 8, 12}:
        return True
    return False


def _focus_houses_by_question(question_text: str) -> List[int]:
    q = str(question_text or "").lower()
    if any(x in q for x in ["marriage", "shaadi", "vivah", "partner"]):
        return [7, 2, 11]
    if any(x in q for x in ["job", "career", "naukri", "profession"]):
        return [10, 6, 11]
    if any(x in q for x in ["money", "wealth", "income", "dhan"]):
        return [2, 11]
    if any(x in q for x in ["health", "disease", "bimari", "rog"]):
        return [1, 6, 8, 12]
    return [1, 9, 10]


def _multi_system_analysis(
    birth_chart: Optional[dict],
    transit_chart: Optional[dict],
    language: str = "hi",
    question_text: str = "",
    mode: str = "natal",
) -> dict:
    if not birth_chart:
        return {}

    hi = str(language).lower() == "hi"
    planets = birth_chart.get("planets", {})
    ph = birth_chart.get("planet_houses", {})
    lagna = birth_chart.get("lagna", {})
    dasha = birth_chart.get("dasha", {})

    lagna_rashi = lagna.get("rashi", "Aries")
    lagna_lord = lagna.get("rashi_lord", _house_lord_for_number(lagna_rashi, 1))
    lord7 = _house_lord_for_number(lagna_rashi, 7)
    lord10 = _house_lord_for_number(lagna_rashi, 10)
    lord2 = _house_lord_for_number(lagna_rashi, 2)
    lord11 = _house_lord_for_number(lagna_rashi, 11)
    lord5 = _house_lord_for_number(lagna_rashi, 5)
    lord6 = _house_lord_for_number(lagna_rashi, 6)
    kp_house_map = _kp_house_sublord_map(birth_chart)
    kp_conn_7 = _kp_sublord_connected_to_houses(birth_chart, 7, {2, 7, 11})
    kp_conn_10 = _kp_sublord_connected_to_houses(birth_chart, 10, {2, 6, 10, 11})
    kp_event_yes = _kp_sublord_connected_to_houses(birth_chart, 10, {2, 6, 10, 11}) or _kp_sublord_connected_to_houses(birth_chart, 7, {2, 7, 11})
    kp_event_no = _kp_sublord_connected_to_houses(birth_chart, 10, {6, 8, 12}) and _kp_sublord_connected_to_houses(birth_chart, 7, {6, 8, 12})

    house_occupants: Dict[int, List[str]] = {i: [] for i in range(1, 13)}
    for p, h in ph.items():
        if h in house_occupants:
            house_occupants[h].append(p)

    benefics = {"Jupiter", "Venus", "Mercury", "Moon"}
    malefics = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}

    def _has_benefic(h: int) -> bool:
        return any(p in benefics for p in house_occupants.get(h, []))

    def _conj(a: str, b: str) -> bool:
        ha = ph.get(a)
        hb = ph.get(b)
        return bool(ha and hb and ha == hb)

    flags = {
        "lagna_lord_strong": _planet_is_strong(lagna_lord, birth_chart),
        "lagna_lord_afflicted": _planet_is_afflicted(lagna_lord, birth_chart),
        "benefics_in_kendra": any(_has_benefic(h) for h in [1, 4, 7, 10]),
        "malefics_in_kendra": any(any(p in malefics for p in house_occupants.get(h, [])) for h in [1, 4, 7, 10]),
        "strong_7th_lord": _planet_is_strong(lord7, birth_chart),
        "benefic_aspect_7th": _has_benefic(7),
        "lord7_in_6_8_12": ph.get(lord7) in {6, 8, 12},
        "venus_strong": _planet_is_strong("Venus", birth_chart),
        "venus_afflicted": _planet_is_afflicted("Venus", birth_chart),
        "rahu_in_7th": ph.get("Rahu") == 7,
        "kp_7th_sublord_connected_2_7_11": kp_conn_7,
        "strong_10th_lord": _planet_is_strong(lord10, birth_chart),
        "saturn_in_10th": ph.get("Saturn") == 10,
        "lord10_in_6th": ph.get(lord10) == 6,
        "lord10_in_7th": ph.get(lord10) == 7,
        "kp_10th_sublord_connected_2_6_10_11": kp_conn_10,
        "lords2_11_strong": _planet_is_strong(lord2, birth_chart) and _planet_is_strong(lord11, birth_chart),
        "jupiter_in_2_or_11": ph.get("Jupiter") in {2, 11},
        "lord2_afflicted": _planet_is_afflicted(lord2, birth_chart),
        "rahu_in_11th": ph.get("Rahu") == 11,
        "house6_afflicted": (_planet_is_afflicted(lord6, birth_chart) or len([p for p in house_occupants.get(6, []) if p in malefics]) >= 1),
        "benefic_in_6th": _has_benefic(6),
        "saturn_rahu_in_6_or_8": (ph.get("Saturn") in {6, 8} and ph.get("Rahu") in {6, 8}),
        "sublord_connected_2_6_10_11": kp_event_yes,
        "sublord_connected_6_8_12": kp_event_no,
        "venus_rahu": _conj("Venus", "Rahu"),
        "jupiter_moon": _conj("Jupiter", "Moon"),
        "saturn_moon": _conj("Saturn", "Moon"),
    }

    transit_ph = (transit_chart or {}).get("planet_houses", {})
    flags.update({
        "jupiter_transit_2_5_9_11": transit_ph.get("Jupiter") in {2, 5, 9, 11},
        "saturn_transit_8_12": transit_ph.get("Saturn") in {8, 12},
        "rahu_transit_2_5_11": transit_ph.get("Rahu") in {2, 5, 11},
        "moon_afflicted_today": transit_ph.get("Moon") in {6, 8, 12},
    })

    all_rules = []
    for _, rules in ASTRO_RULEBOOK.items():
        all_rules.extend(rules)
    scored = _condition_score(all_rules, flags)

    # Jaimini core: Atmakaraka + Karakamsa + directional purpose.
    ak_candidates = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
    ak = max(ak_candidates, key=lambda p: float((planets.get(p) or {}).get("longitude", 0.0)))
    ak_nav = str((planets.get(ak) or {}).get("navamsha_sign", ""))
    jaimini_score = 0.65 if ph.get(ak) in {1, 5, 9, 10, 11} else 0.45

    parashar_score = scored["system_scores"].get("parashar", 0.5)
    kp_score = scored["system_scores"].get("kp", 0.5)
    bhrigu_score = scored["system_scores"].get("bhrigu", 0.5)

    combined = (
        parashar_score * SYSTEM_WEIGHTS["parashar"]
        + kp_score * SYSTEM_WEIGHTS["kp"]
        + jaimini_score * SYSTEM_WEIGHTS["jaimini"]
        + bhrigu_score * SYSTEM_WEIGHTS["bhrigu"]
    )

    confidence_pct = int(round(max(0.0, min(1.0, combined)) * 100))
    if combined > 0.7:
        level = "Strong Yes"
    elif combined >= 0.4:
        level = "Medium"
    else:
        level = "Weak / No"

    activated_houses = _focus_houses_by_question(question_text)
    if not str(question_text or "").strip():
        if mode == "gochar":
            activated_houses = [1, 4, 7, 10, 11]
        elif mode == "prashna":
            activated_houses = [7, 10, 11]
        else:
            activated_houses = [1, 5, 9, 10]

    kp_full_table = _kp_full_cusp_table(birth_chart, set(activated_houses))
    kp_ranked = sorted(kp_full_table, key=lambda x: float(x.get("event_suitability", 0.0)), reverse=True)
    kp_top = kp_ranked[:5]
    maha = str(dasha.get("mahadasha", "?"))
    antar = str(dasha.get("antardasha", "?"))
    antar_end = str(dasha.get("antardasha_end", "Unknown"))
    kp_window_start = datetime.now().strftime("%Y-%m-%d")
    kp_window_end = str(antar_end)

    if hi:
        life_overview = (
            f"संरचना→अर्थ→समय→पुष्टि: लग्न {lagna.get('rashi_hi', lagna.get('rashi', ''))} और लग्नेश {lagna_lord} की शक्ति पर जीवन-दिशा आधारित है। "
            f"जैमिनी में आत्मकारक {ak} तथा कारकांश {ak_nav} से जीवन-उद्देश्य की धारा स्पष्ट होती है।"
        )
        event_timing = (
            f"केपी समय-विंडो: {maha}/{antar} प्रभाव में प्रमुख ट्रिगर अवधि {antar_end} तक सक्रिय मानी जाएगी। "
            f"प्रश्न-आधारित सक्रिय भाव: {', '.join(str(h) for h in activated_houses)}। "
            f"केपी कुस्प उप-स्वामी संकेत: ७वां={kp_house_map.get(7, {}).get('sublord', '?')}, १०वां={kp_house_map.get(10, {}).get('sublord', '?')}।"
        )
        confirmation = (
            f"भृगु-पुष्टि: तेज संयोजन संकेतों के साथ समेकित विश्वास स्तर {confidence_pct}% ({level})। "
            f"विरोधी नियम बढ़ने पर विश्वास स्तर स्वतः घटाया गया है।"
        )
    else:
        life_overview = (
            f"Structure->Meaning->Timing->Confirmation: life direction is anchored in Lagna strength and Lagna lord {lagna_lord}. "
            f"Jaimini layer shows Atmakaraka {ak} with Karakamsa {ak_nav} for purpose-direction mapping."
        )
        event_timing = (
            f"KP timing window: major trigger period runs under {maha}/{antar} up to {antar_end}. "
            f"Question-activated houses: {', '.join(str(h) for h in activated_houses)}. "
            f"KP cusp sublords: 7th={kp_house_map.get(7, {}).get('sublord', '?')}, 10th={kp_house_map.get(10, {}).get('sublord', '?')}."
        )
        confirmation = (
            f"Bhrigu confirmation: combined confidence {confidence_pct}% ({level}). "
            f"Conflicting-rule pressure is already applied in confidence reduction."
        )

    return {
        "framework": "Structure -> Meaning -> Timing -> Confirmation (Parashar -> Jaimini -> KP -> Bhrigu)",
        "mode": mode,
        "life_overview": life_overview,
        "event_timing": event_timing,
        "confirmation_notes": confirmation,
        "activated_houses": activated_houses,
        "scores": {
            "parashar": round(parashar_score, 3),
            "kp": round(kp_score, 3),
            "jaimini": round(jaimini_score, 3),
            "bhrigu": round(bhrigu_score, 3),
            "combined": round(combined, 3),
            "confidence_percent": confidence_pct,
            "confidence_level": level,
        },
        "kp_core": {
            "cusp_sublords": {
                "7": kp_house_map.get(7, {}),
                "10": kp_house_map.get(10, {}),
            },
            "full_cusp_table": kp_full_table,
            "top_event_houses": kp_top,
            "event_windows": {
                "start": kp_window_start,
                "end": kp_window_end,
            },
            "house_connections": {
                "7th_to_2_7_11": kp_conn_7,
                "10th_to_2_6_10_11": kp_conn_10,
                "event_yes_pattern": kp_event_yes,
                "event_no_pattern": kp_event_no,
            },
        },
        "jaimini_core": {
            "atmakaraka": ak,
            "karakamsa": ak_nav,
        },
        "rule_hits": scored["hits"],
    }


def _compute_vedic_chart(dob: str, tob: str,
                          lat: Optional[float] = None,
                          lng: Optional[float] = None) -> dict:
    """
    Full Vedic birth chart via Swiss Ephemeris (Lahiri ayanamsa).
    Returns planets, lagna, houses, Vimshottari dasha + decade mapping.
    """
    tob_clean = tob.strip()
    if len(tob_clean) == 5:
        tob_clean += ":00"

    tf = TimezoneFinder()
    tz_name = (tf.timezone_at(lat=float(lat), lng=float(lng)) if lat is not None and lng is not None
               else None) or "Asia/Kolkata"
    tz = ZoneInfo(tz_name)

    dt_naive = datetime.strptime(f"{dob} {tob_clean}", "%Y-%m-%d %H:%M:%S")
    dt_local = dt_naive.replace(tzinfo=tz)
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

    jd = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                    dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0)

    swe.set_sid_mode(swe.SIDM_LAHIRI)
    ayanamsa = swe.get_ayanamsa(jd)

    PLANET_IDS = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS,
        "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER, "Venus": swe.VENUS,
        "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE,
    }

    planets_data = {}
    for name, pid in PLANET_IDS.items():
        result, _ = swe.calc_ut(jd, pid)
        sid_lon = (result[0] - ayanamsa) % 360.0
        rashi_idx = int(sid_lon / 30)
        deg_in_sign = sid_lon % 30
        nak_num = int(sid_lon / NAK_SPAN)
        pada = int((sid_lon % NAK_SPAN) / (NAK_SPAN / 4)) + 1
        dignity = _planet_dignity(name, SIGNS[rashi_idx])
        nav_idx = _navamsha_sign_index(rashi_idx, deg_in_sign)
        planets_data[name] = {
            "longitude": round(sid_lon, 4),
            "rashi": SIGNS[rashi_idx],
            "rashi_hi": SIGNS_HI[rashi_idx],
            "rashi_num": rashi_idx + 1,
            "degree_in_sign": round(deg_in_sign, 2),
            "navamsha_sign": SIGNS[nav_idx],
            "navamsha_sign_hi": SIGNS_HI[nav_idx],
            "nakshatra": NAKSHATRAS[nak_num],
            "nakshatra_lord": NAKSHATRA_LORDS[nak_num],
            "pada": pada,
            "dignity": dignity,
        }

    # Ketu = Rahu + 180Â°
    rahu_lon = planets_data["Rahu"]["longitude"]
    ketu_lon = (rahu_lon + 180.0) % 360.0
    k_rashi = int(ketu_lon / 30)
    k_deg = ketu_lon % 30
    k_nav_idx = _navamsha_sign_index(k_rashi, k_deg)
    k_nak = int(ketu_lon / NAK_SPAN)
    k_pada = int((ketu_lon % NAK_SPAN) / (NAK_SPAN / 4)) + 1
    planets_data["Ketu"] = {
        "longitude": round(ketu_lon, 4),
        "rashi": SIGNS[k_rashi], "rashi_hi": SIGNS_HI[k_rashi],
        "rashi_num": k_rashi + 1,
        "degree_in_sign": round(k_deg, 2),
        "navamsha_sign": SIGNS[k_nav_idx],
        "navamsha_sign_hi": SIGNS_HI[k_nav_idx],
        "nakshatra": NAKSHATRAS[k_nak],
        "nakshatra_lord": NAKSHATRA_LORDS[k_nak],
        "pada": k_pada, "dignity": "",
    }

    # â”€â”€ Lagna & house positions â”€â”€
    lagna = None
    planet_houses = {}
    house_cusps_sidereal: List[float] = []
    if lat is not None and lng is not None:
        cusps, ascmc = swe.houses(jd, float(lat), float(lng), b"P")
        asc_sid = (ascmc[0] - ayanamsa) % 360.0
        house_cusps_sidereal = [round((float(c) - ayanamsa) % 360.0, 4) for c in list(cusps[:12])]
        a_rashi = int(asc_sid / 30)
        a_nak = int(asc_sid / NAK_SPAN)
        a_deg = asc_sid % 30
        a_nav_idx = _navamsha_sign_index(a_rashi, a_deg)
        lagna = {
            "longitude": round(asc_sid, 4),
            "rashi": SIGNS[a_rashi], "rashi_hi": SIGNS_HI[a_rashi],
            "rashi_lord": SIGN_LORDS.get(SIGNS[a_rashi], "Unknown"),
            "degree_in_sign": round(a_deg, 2),
            "navamsha_sign": SIGNS[a_nav_idx],
            "navamsha_sign_hi": SIGNS_HI[a_nav_idx],
            "nakshatra": NAKSHATRAS[a_nak],
        }
        lagna_rashi_num = a_rashi + 1  # 1-indexed (Aries=1 ... Pisces=12)
        for pname, pdata in planets_data.items():
            # Whole Sign House system (standard Vedic / Parashari)
            # House = how many signs forward from Lagna sign, 1-based
            planet_houses[pname] = (pdata["rashi_num"] - lagna_rashi_num) % 12 + 1

    # â”€â”€ Vimshottari Dasha â”€â”€
    moon_lon = planets_data["Moon"]["longitude"]
    moon_nak = int(moon_lon / NAK_SPAN)
    birth_nak_lord = NAKSHATRA_LORDS[moon_nak]
    fraction_done = (moon_lon % NAK_SPAN) / NAK_SPAN
    years_consumed = fraction_done * DASHA_YEARS[birth_nak_lord]

    lord_idx = DASHA_ORDER.index(birth_nak_lord)
    dob_date = datetime.strptime(dob, "%Y-%m-%d")
    today = datetime.now()

    sequences: List[dict] = []
    cur = dob_date
    for i in range(27):  # 3 full cycles
        lord = DASHA_ORDER[(lord_idx + i) % 9]
        yrs = DASHA_YEARS[lord] - (years_consumed if i == 0 else 0)
        end = cur + timedelta(days=yrs * 365.25)
        sequences.append({"lord": lord, "start": cur, "end": end})
        cur = end
        if cur > today + timedelta(days=40 * 365):
            break

    cur_maha = next((s for s in sequences if s["start"] <= today <= s["end"]), None)
    dasha_info: dict = {"mahadasha": "Unknown", "antardasha": "Unknown"}

    if cur_maha:
        ml = cur_maha["lord"]
        m_yrs = (cur_maha["end"] - cur_maha["start"]).days / 365.25
        li2 = DASHA_ORDER.index(ml)
        ad = cur_maha["start"]
        for i in range(9):
            al = DASHA_ORDER[(li2 + i) % 9]
            a_yrs = (DASHA_YEARS[al] / 120.0) * m_yrs
            a_end = ad + timedelta(days=a_yrs * 365.25)
            if ad <= today <= a_end:
                li3 = DASHA_ORDER.index(al)
                pd = ad
                ptd = "?"
                for j in range(9):
                    pl = DASHA_ORDER[(li3 + j) % 9]
                    p_yrs = (DASHA_YEARS[pl] / 120.0) * a_yrs
                    p_end = pd + timedelta(days=p_yrs * 365.25)
                    if pd <= today <= p_end:
                        ptd = pl
                        break
                    pd = p_end
                dasha_info = {
                    "mahadasha": ml,
                    "antardasha": al,
                    "pratyantardasha": ptd,
                    "mahadasha_end": cur_maha["end"].strftime("%b %Y"),
                    "antardasha_end": a_end.strftime("%b %Y"),
                    "years_remaining_in_maha": round((cur_maha["end"] - today).days / 365.25, 1),
                    "months_remaining_in_antar": round((a_end - today).days / 30.44, 1),
                }
                break
            ad = a_end

    # â”€â”€ Dasha lords for each decade of life â”€â”€
    dasha_by_decade: dict = {}
    for start_age in range(0, 91, 10):
        d_start = dob_date + timedelta(days=start_age * 365.25)
        d_end = dob_date + timedelta(days=(start_age + 10) * 365.25)
        lords: List[str] = []
        for seq in sequences:
            if seq["end"] < d_start or seq["start"] > d_end:
                continue
            ov_start = max(seq["start"], d_start)
            ov_end = min(seq["end"], d_end)
            yrs_overlap = (ov_end - ov_start).days / 365.25
            lords.append(f"{seq['lord']}({round(yrs_overlap,1)}yr)")
        dasha_by_decade[f"{start_age}-{start_age+10}"] = (
            ", ".join(lords) if lords else "Unknown"
        )

    return {
        "lagna": lagna,
        "planets": planets_data,
        "planet_houses": planet_houses,
        "house_cusps_sidereal": house_cusps_sidereal,
        "dasha": dasha_info,
        "dasha_sequences": sequences,
        "dasha_by_decade": dasha_by_decade,
        "ayanamsa": round(ayanamsa, 4),
    }


def _build_computed_houses(chart: dict, language: str) -> List[dict]:
    """
    Build 12 fully-computed house records from Swiss Ephemeris chart data.
    These are authoritative — AI must NOT contradict them.
    """
    lagna = chart.get("lagna")
    planets = chart.get("planets", {})
    ph = chart.get("planet_houses", {})
    hi = (language == "hi")

    if not lagna:
        return []

    try:
        lagna_sign_idx = SIGNS.index(lagna["rashi"])
    except ValueError:
        lagna_sign_idx = 0

    HOUSE_NAMES_HI = [
        "लग्न भाव (Lagna)", "धन भाव (Dhana)", "पराक्रम भाव (Parakrama)",
        "सुख भाव (Sukha)", "पुत्र भाव (Putra)", "रोग भाव (Roga)",
        "कलत्र भाव (Kalatra)", "मृत्यु भाव (Mrityu)", "भाग्य भाव (Bhagya)",
        "कर्म भाव (Karma)", "लाभ भाव (Labha)", "व्यय भाव (Vyaya)"
    ]
    HOUSE_NAMES_EN = [
        "Lagna (Self)", "Dhana (Wealth)", "Parakrama (Siblings/Courage)",
        "Sukha (Home/Mother)", "Putra (Children/Intellect)", "Roga (Health/Service)",
        "Kalatra (Marriage/Partner)", "Mrityu (Transformation)", "Bhagya (Luck/Dharma)",
        "Karma (Career/Status)", "Labha (Gains/Network)", "Vyaya (Loss/Moksha)"
    ]

    results = []
    for h_num in range(1, 13):
        sign_idx = (lagna_sign_idx + h_num - 1) % 12
        sign_en  = SIGNS[sign_idx]
        sign_h   = SIGNS_HI[sign_idx]
        lord     = SIGN_LORDS.get(sign_en, "?")
        lord_house = ph.get(lord)

        # Planets in this house
        occupants = [p for p, hn in ph.items() if hn == h_num]

        # Build rich occupant description
        occ_desc = []
        for p in occupants:
            pd = planets.get(p, {})
            dig = pd.get("dignity", "")
            deg = pd.get("degree_in_sign", "?")
            nak = pd.get("nakshatra", "?")
            pada = pd.get("pada", "?")
            nak_lord = pd.get("nakshatra_lord", "?")
            if hi:
                s = (f"{p} — {pd.get('rashi_hi', sign_h)} {deg}°, "
                     f"नक्षत्र: {nak} (पद {pada}, {nak_lord})")
            else:
                s = (f"{p} — {pd.get('rashi', sign_en)} {deg}°, "
                     f"Nakshatra: {nak} (Pada {pada}, lord {nak_lord})")
            if dig:
                s += f" [{dig}]"
            occ_desc.append(s)

        # Where is the house lord sitting?
        if lord_house:
            if hi:
                lord_pos = f"{lord} (भावेश) — {lord_house}वें भाव में है"
            else:
                lord_pos = f"{lord} (house lord) is in house {lord_house}"
        else:
            lord_pos = ""

        if hi:
            name = HOUSE_NAMES_HI[h_num - 1]
            if occ_desc:
                analysis = (f"[Swiss Ephemeris आधारित तथ्य] राशि: {sign_h} | भावेश: {lord} | "
                            f"ग्रह: {'; '.join(occ_desc)}")
            else:
                analysis = f"[Swiss Ephemeris आधारित तथ्य] राशि: {sign_h} | भावेश: {lord} | ग्रह: कोई नहीं"
            if lord_pos:
                analysis += f" | {lord_pos}"
        else:
            name = HOUSE_NAMES_EN[h_num - 1]
            if occ_desc:
                analysis = (f"[Computed Fact] Sign: {sign_en} | Lord: {lord} | "
                            f"Planets: {'; '.join(occ_desc)}")
            else:
                analysis = f"[Computed Fact] Sign: {sign_en} | Lord: {lord} | Planets: Empty"
            if lord_pos:
                analysis += f" | {lord_pos}"

        results.append({
            "house": h_num,
            "name": name,
            "sign": sign_en,
            "sign_hi": sign_h,
            "lord": lord,
            "lord_house": lord_house,
            "occupants": occupants,
            "analysis": analysis,   # factual — computed, not AI
            "advice": "",           # AI fills this
        })
    return results


def _chart_to_prompt_text(chart: dict, language: str) -> str:
    """Convert computed chart dict into rich, structured text for the AI prompt."""
    lagna = chart.get("lagna")
    planets = chart.get("planets", {})
    ph = chart.get("planet_houses", {})
    dasha = chart.get("dasha", {})
    dbd = chart.get("dasha_by_decade", {})
    hi = (language == "hi")

    lines = ["", "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•",
             "  SWISS EPHEMERIS â€” ACTUAL COMPUTED VEDIC BIRTH CHART",
             "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"]

    if lagna:
        ll = lagna.get("rashi_lord", "?")
        if hi:
            lines.append(f"  Lagna : {lagna['rashi_hi']} ({lagna['rashi']}) | "
                         f"{lagna['degree_in_sign']}Â° | Nakshatra : {lagna['nakshatra']} | "
                         f"Lagnesh : {ll}")
        else:
            lines.append(f"  Lagna : {lagna['rashi']} {lagna['degree_in_sign']}Â° | "
                         f"Nakshatra : {lagna['nakshatra']} | Lagna Lord : {ll}")
    else:
        lines.append("  Lagna : Could not compute (coordinates missing)")

    lines.append("")
    lines.append("  Grahas (Lahiri Ayanamsa, Sidereal):")
    for pname, pd_data in planets.items():
        house_str = f" | {'Bhava' if hi else 'House'} {ph[pname]}" if pname in ph else ""
        dig = f" | {pd_data['dignity']}" if pd_data.get("dignity") else ""
        if hi:
            lines.append(
                f"    {pname:8s}: {pd_data['rashi_hi']:10s} {pd_data['degree_in_sign']:5.2f}Â° | "
                f"Nakshatra: {pd_data['nakshatra']:20s} Pada {pd_data['pada']}"
                f"{house_str}{dig}"
            )
        else:
            lines.append(
                f"    {pname:8s}: {pd_data['rashi']:13s} {pd_data['degree_in_sign']:5.2f}° | "
                f"Nakshatra: {pd_data['nakshatra']:20s} Pada {pd_data['pada']}"
                f"{house_str}{dig}"
            )

    # ── House Occupancy Table (authoritative) ──────────────────────────────
    if ph and lagna:
        try:
            lagna_sign_idx = SIGNS.index(lagna["rashi"])
        except ValueError:
            lagna_sign_idx = 0
        lines.append("")
        if hi:
            lines.append("  *** BHAVA-GRAHA STHITI (AUTHORITATIVE — YEH DATA FOLLOW KARO) ***")
            lines.append("  Har bhav me kaunse grah hain (whole sign house / Parashari paddhati):")
        else:
            lines.append("  *** HOUSE OCCUPANCY TABLE (AUTHORITATIVE — FOLLOW THIS EXACTLY) ***")
            lines.append("  Which planets are in each house (Whole Sign / Parashari system):")
        for h_num in range(1, 13):
            sign_idx = (lagna_sign_idx + h_num - 1) % 12
            sign     = SIGNS[sign_idx]
            sign_h   = SIGNS_HI[sign_idx]
            lord     = SIGN_LORDS.get(sign, "?")
            occupants = [p for p, hn in ph.items() if hn == h_num]
            occ_str = ", ".join(occupants) if occupants else ("Koi grah nahi" if hi else "Empty")
            if hi:
                lines.append(f"    Bhava {h_num:2d} ({sign_h:10s} | Bhavesh: {lord:8s}): {occ_str}")
            else:
                lines.append(f"    House {h_num:2d} ({sign:13s} | Lord: {lord:8s}): {occ_str}")
        if hi:
            lines.append("  ⚠ WARNING: Upar ki is table ke VIRUDDH koi bhi grah placement mat likhna.")
        else:
            lines.append("  ⚠ WARNING: Do NOT write any planet in a house that contradicts the table above.")

    lines.append("")
    lines.append("  Vimshottari Dasha (Current):")
    if dasha.get("mahadasha") not in ("Unknown", None):
        maha = dasha['mahadasha']
        antar = dasha.get('antardasha', '?')
        ptd = dasha.get('pratyantardasha', '?')
        if hi:
            lines.append(f"    Mahadasha     : {maha}  (ends {dasha.get('mahadasha_end','?')}, {dasha.get('years_remaining_in_maha','?')} saal shesh)")
            lines.append(f"    Antardasha    : {antar}  (ends {dasha.get('antardasha_end','?')}, {dasha.get('months_remaining_in_antar','?')} maah shesh)")
            lines.append(f"    Pratyantardasha: {ptd}")
        else:
            lines.append(f"    Mahadasha     : {maha}  (ends {dasha.get('mahadasha_end','?')}, {dasha.get('years_remaining_in_maha','?')} yrs left)")
            lines.append(f"    Antardasha    : {antar}  (ends {dasha.get('antardasha_end','?')}, {dasha.get('months_remaining_in_antar','?')} mo left)")
            lines.append(f"    Pratyantardasha: {ptd}")
    else:
        lines.append("    Dasha: Could not compute")

    if dbd:
        lines.append("")
        lines.append(f"  {'Dashakiya Jeevan Rekha' if hi else 'Dasha Timeline by Decade'}:")
        for age_range, lords in dbd.items():
            lines.append(f"    Age {age_range:5s} : {lords}")

    lines.append("")
    if hi:
        lines.append("  âš  YE WAASTAVIK ASTRONOMICAL DATA HAI â€” Swiss Ephemeris se computed.")
        lines.append("  âš  Har prediction is data ke SPECIFIC graha/bhava/naksha ke aadhar par honi chahiye.")
        lines.append("  âš  Koi bhi generic ya vague prediction kabool nahi hai.")
    else:
        lines.append("  âš  THIS IS REAL ASTRONOMICAL DATA â€” computed via Swiss Ephemeris.")
        lines.append("  âš  Every prediction MUST cite the specific planet/house/nakshatra/dasha causing it.")
        lines.append("  âš  Generic, vague or chart-unsupported predictions are NOT acceptable.")
    lines.append("â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•")
    lines.append("")
    return "\n".join(lines)

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY", "").strip()
openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
model = None
openai_client = None
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "150"))
KUNDLI_MODEL_TIMEOUT_SECONDS = float(
    os.getenv("KUNDLI_MODEL_TIMEOUT_SECONDS", str(min(MODEL_TIMEOUT_SECONDS, 55.0)))
)
OPENAI_MODEL = "gpt-4o-mini"

# --- OpenAI init (primary) ---
if openai_api_key and _OpenAIClient is not None:
    try:
        openai_client = _OpenAIClient(api_key=openai_api_key)
        print(f"INFO: OpenAI client ready — using {OPENAI_MODEL} as primary model")
    except Exception as _oe:
        print("WARNING: OpenAI init failed:", repr(_oe))
        openai_client = None
else:
    print("INFO: OPENAI_API_KEY not set — will use Gemini")

# --- Gemini init (fallback) ---
PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
    "gemini-pro",
]

if api_key:
    try:
        genai.configure(api_key=api_key)
        available = [m.name for m in genai.list_models()
                     if "generateContent" in m.supported_generation_methods]
        chosen = None
        for pref in PREFERRED_MODELS:
            for avail in available:
                if pref in avail:
                    chosen = avail
                    break
            if chosen:
                break
        if not chosen and available:
            chosen = available[0]
        if chosen:
            model = genai.GenerativeModel(chosen)
            print(f"INFO: Gemini fallback model: {chosen}")
        else:
            print("WARNING: No Gemini generateContent-capable model found")
    except Exception as e:
        print("WARNING: Gemini model init failed:", repr(e))
else:
    print("WARNING: GOOGLE_API_KEY missing in backend/.env")

app = FastAPI()

# CORS: lock down in production by setting ALLOWED_ORIGINS to a comma-separated
# list of origins (e.g. "https://myapp.com,https://www.myapp.com").
# Defaults to "*" for local development.
_allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*").strip()
if _allowed_origins_raw and _allowed_origins_raw != "*":
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
else:
    _allowed_origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Authentication ──────────────────────────────────────────────────────────
# Real credential-based auth using only the Python standard library:
#   - passwords stored as PBKDF2-HMAC-SHA256 hashes (never plaintext)
#   - stateless, HMAC-signed bearer tokens with an expiry
#   - user records kept in a local SQLite file (backend/users.db)
#
# Set AUTH_SECRET_KEY in backend/.env so tokens survive a server restart.
# If unset, a random secret is generated per process (tokens invalidate on
# restart — fine for local dev, not for production).
AUTH_SECRET = os.getenv("AUTH_SECRET_KEY", "").strip() or secrets.token_hex(32)
if not os.getenv("AUTH_SECRET_KEY", "").strip():
    print("WARNING: AUTH_SECRET_KEY not set — using a random per-process secret. "
          "Set AUTH_SECRET_KEY in backend/.env to keep users logged in across restarts.")
AUTH_DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
AUTH_TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))
_PBKDF2_ITERATIONS = 200_000


def _auth_db() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            pw_salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def _hash_password(password: str, salt: Optional[str] = None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return base64.b64encode(dk).decode("ascii"), salt


def _verify_password(password: str, pw_hash: str, salt: str) -> bool:
    calc, _ = _hash_password(password, salt)
    return hmac.compare_digest(calc, str(pw_hash))


def _make_token(identifier: str) -> str:
    exp = int(time.time()) + AUTH_TOKEN_TTL_SECONDS
    payload = f"{identifier}|{exp}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_token(token: str) -> Optional[str]:
    try:
        payload_b64, sig = str(token).split(".", 1)
        expected = hmac.new(AUTH_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        pad = "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64 + pad).decode("utf-8")
        identifier, exp = payload.split("|", 1)
        if int(exp) < int(time.time()):
            return None
        return identifier
    except Exception:
        return None


class AuthInput(BaseModel):
    identifier: str
    password: str


@app.post("/auth/signup")
async def auth_signup(payload: AuthInput):
    identifier = str(payload.identifier or "").strip().lower()
    password = str(payload.password or "")
    if not identifier or not password:
        return {"error": "Email/mobile aur password dono zaroori hain."}
    if len(password) < 6:
        return {"error": "Password kam se kam 6 characters ka hona chahiye."}

    pw_hash, salt = _hash_password(password)
    conn = _auth_db()
    try:
        conn.execute(
            "INSERT INTO users (identifier, pw_hash, pw_salt, created_at) VALUES (?, ?, ?, ?)",
            (identifier, pw_hash, salt, datetime.now().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {"error": "Yeh account pehle se maujood hai. Kripya login karein."}
    except Exception as e:
        print("AUTH SIGNUP ERROR:", repr(e))
        return {"error": "Account banane mein technical dikkat aayi. Dubara try karein."}
    finally:
        conn.close()

    return {"token": _make_token(identifier), "identifier": identifier}


@app.post("/auth/login")
async def auth_login(payload: AuthInput):
    identifier = str(payload.identifier or "").strip().lower()
    password = str(payload.password or "")
    if not identifier or not password:
        return {"error": "Email/mobile aur password dono zaroori hain."}

    conn = _auth_db()
    try:
        row = conn.execute(
            "SELECT pw_hash, pw_salt FROM users WHERE identifier = ?", (identifier,)
        ).fetchone()
    except Exception as e:
        print("AUTH LOGIN ERROR:", repr(e))
        return {"error": "Login mein technical dikkat aayi. Dubara try karein."}
    finally:
        conn.close()

    if not row or not _verify_password(password, row[0], row[1]):
        return {"error": "Galat email/mobile ya password."}

    return {"token": _make_token(identifier), "identifier": identifier}


@app.get("/auth/me")
async def auth_me(token: str = ""):
    identifier = _verify_token(token)
    if not identifier:
        return {"authenticated": False}
    return {"authenticated": True, "identifier": identifier}


# ─── Endpoint protection: auth enforcement + rate limiting ───────────────────
# AUTH_ENFORCE=true (default) requires a valid bearer token on the astrology and
# market endpoints. Set AUTH_ENFORCE=false to allow anonymous access (e.g. for
# local testing). RATE_LIMIT_PER_MINUTE caps requests per client IP (0 disables).
AUTH_ENFORCE = os.getenv("AUTH_ENFORCE", "true").strip().lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
_RATE_BUCKET: Dict[str, List[float]] = {}


def require_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """FastAPI dependency: verify the Authorization: Bearer <token> header."""
    if not AUTH_ENFORCE:
        return None
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    identifier = _verify_token(token)
    if not identifier:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in again.")
    return identifier


def rate_limit(request: Request) -> None:
    """FastAPI dependency: simple in-memory sliding-window limit per client IP."""
    if RATE_LIMIT_PER_MINUTE <= 0:
        return
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    now = time.time()
    window_start = now - 60.0
    bucket = [t for t in _RATE_BUCKET.get(client_ip, []) if t >= window_start]
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")
    bucket.append(now)
    _RATE_BUCKET[client_ip] = bucket


async def _geocode_place(place_name: str):
    """Return (lat, lng) for a city name using Nominatim; returns (None, None) on failure."""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"format": "json", "q": place_name, "limit": 1}
        headers = {"User-Agent": "MedhaAI-Jyotish/1.0", "Accept-Language": "en"}
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as geo_err:
        print("GEOCODE WARNING:", repr(geo_err))
    return None, None

class UserInput(BaseModel):
    first_name: str
    dob: str
    tob: str
    place: str
    selected_number: int
    language: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class SectionQAInput(BaseModel):
    section: str
    question: str
    language: str = "hi"
    context: Optional[str] = ""
    answer_mode: Optional[str] = "short"


class TeziMandiInput(BaseModel):
    first_name: str
    dob: str
    tob: str
    place: str
    product: str
    target_date: str
    language: str = "hi"
    lat: Optional[float] = None
    lng: Optional[float] = None


ROMAN_HINDI_MARKERS = {
    "kya", "kaise", "kab", "kyu", "kyun", "mera", "meri", "mere", "mujhe", "aap",
    "hai", "hain", "ho", "hoga", "hogi", "kar", "karu", "karun", "nahi", "nahin",
    "agar", "aur", "par", "ke", "ki", "ko", "se", "mein", "main", "ka", "tha", "thi"
}


def _detect_question_style(question: str, fallback_language: str = "hi") -> str:
    q = str(question or "").strip()
    if not q:
        return "hi" if str(fallback_language).lower() == "hi" else "en"

    if re.search(r"[\u0900-\u097F]", q):
        return "hi"

    tokens = re.findall(r"[a-zA-Z']+", q.lower())
    if not tokens:
        return "hi" if str(fallback_language).lower() == "hi" else "en"

    roman_hi_hits = sum(1 for t in tokens if t in ROMAN_HINDI_MARKERS)
    if roman_hi_hits >= 2:
        return "hinglish"

    return "en"


def _style_instruction(question_style: str) -> str:
    style = str(question_style or "").lower()
    if style == "hi":
        return (
            "Language style lock: Respond ONLY in Hindi using Devanagari script. "
            "Do not use Roman Hindi or English words except standard proper nouns."
        )
    if style == "hinglish":
        return (
            "Language style lock: Respond in Hinglish (Roman script only, Hindi-English natural mix). "
            "Do NOT use Devanagari script."
        )
    return (
        "Language style lock: Respond ONLY in English. "
        "Do not use Hindi/Devanagari words or Roman Hindi phrases."
    )


def _answer_matches_style(answer: str, question_style: str) -> bool:
    text = str(answer or "")
    has_dev = bool(re.search(r"[\u0900-\u097F]", text))
    has_lat = bool(re.search(r"[A-Za-z]", text))
    style = str(question_style or "").lower()

    if style == "hi":
        return has_dev and not has_lat
    if style == "en":
        return has_lat and not has_dev
    if style == "hinglish":
        return has_lat and not has_dev
    return True


async def generate_content_with_timeout(prompt: str, generation_config=None, timeout_seconds: Optional[float] = None):
    effective_timeout = timeout_seconds if timeout_seconds is not None else MODEL_TIMEOUT_SECONDS

    # --- OpenAI primary ---
    if openai_client is not None:
        try:
            def _openai_call():
                resp = openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=4096,
                )
                return resp.choices[0].message.content or ""
            result_text = await asyncio.wait_for(
                asyncio.to_thread(_openai_call),
                timeout=effective_timeout,
            )
            # Wrap in an object with .text so callers work unchanged
            class _Resp:
                def __init__(self, t): self.text = t
            return _Resp(result_text)
        except Exception as _oe:
            print("WARNING: OpenAI call failed, falling back to Gemini:", repr(_oe))

    # --- Gemini fallback ---
    if model is None:
        raise RuntimeError("Guru Ji is currently unavailable — set OPENAI_API_KEY or GOOGLE_API_KEY in backend/.env")

    kwargs = {}
    if generation_config is not None:
        kwargs["generation_config"] = generation_config

    return await asyncio.wait_for(
        asyncio.to_thread(model.generate_content, prompt, **kwargs),
        timeout=effective_timeout,
    )


def _planet_strength_score(planet_name: str, pdata: dict, house_num: Optional[int]) -> int:
    score = 0
    dignity = str(pdata.get("dignity", ""))

    if "Exalted" in dignity or "Own Sign" in dignity:
        score += 2
    if "Debilitated" in dignity:
        score -= 2

    if house_num in {2, 6, 10, 11}:
        score += 1
    if house_num in {8, 12}:
        score -= 1

    # Saturn/Mars in 6/10 can still show market momentum and active trend.
    if planet_name in {"Saturn", "Mars"} and house_num in {6, 10}:
        score += 1

    return score


def _product_karaka_planets(product: str) -> List[str]:
    p = (product or "").strip().lower()
    mapping = {
        "gold": ["Venus", "Jupiter", "Moon"],
        "silver": ["Moon", "Venus", "Mercury"],
        "crude": ["Mars", "Saturn", "Rahu"],
        "crude oil": ["Mars", "Saturn", "Rahu"],
        "natural gas": ["Mercury", "Rahu", "Moon"],
        "copper": ["Mars", "Mercury", "Saturn"],
        "zinc": ["Saturn", "Mars", "Mercury"],
        "aluminium": ["Saturn", "Mars", "Mercury"],
        "cotton": ["Moon", "Venus", "Jupiter"],
        "soybean": ["Jupiter", "Moon", "Mercury"],
        "wheat": ["Jupiter", "Sun", "Moon"],
        "rice": ["Moon", "Venus", "Jupiter"],
        "sugar": ["Venus", "Moon", "Mercury"],
        "chana": ["Jupiter", "Mercury", "Moon"],
        "nifty": ["Sun", "Mercury", "Jupiter", "Rahu"],
        "banknifty": ["Sun", "Mercury", "Jupiter", "Saturn"],
        "bank nifty": ["Sun", "Mercury", "Jupiter", "Saturn"],
        "equity": ["Sun", "Mercury", "Jupiter", "Rahu"],
        "crypto": ["Rahu", "Mercury", "Mars"],
        "bitcoin": ["Rahu", "Mercury", "Mars"],
    }

    for key, planets in mapping.items():
        if key in p:
            return planets
    return ["Mercury", "Moon", "Jupiter"]


def _market_prediction_from_engine(transit_chart: dict, birth_chart: Optional[dict] = None) -> dict:
    cfg = (ENGINE_CONFIG.get("market_prediction", {}) or {}).get("future_logic", {}) or {}
    tph = transit_chart.get("planet_houses", {}) if isinstance(transit_chart, dict) else {}

    moon_h = tph.get("Moon")
    mercury_strong = _planet_is_strong("Mercury", transit_chart) if transit_chart else False

    trend_flags = {
        "jupiter_transit_supports_2_5_11": tph.get("Jupiter") in {2, 5, 11},
        "saturn_transit_afflicts_2_11": tph.get("Saturn") in {2, 11},
        "saturn_8_12_from_moon": bool(moon_h and tph.get("Saturn") in {((moon_h + 7 - 1) % 12) + 1, ((moon_h + 11 - 1) % 12) + 1}),
    }
    trigger_flags = {
        "kp_sublord_connected_2_5_11": _kp_sublord_connected_to_houses(transit_chart, 11, {2, 5, 11}),
        "kp_sublord_connected_6_8_12": _kp_sublord_connected_to_houses(transit_chart, 11, {6, 8, 12}),
    }
    intraday_flags = {
        "moon_in_11": moon_h == 11,
        "mercury_strong": mercury_strong,
        "moon_afflicted_saturn_rahu": bool(
            moon_h in {6, 8, 12}
            or tph.get("Moon") == tph.get("Saturn")
            or tph.get("Moon") == tph.get("Rahu")
        ),
    }

    trend_score = 0.0
    for rule in cfg.get("trend", []):
        cond = str(rule.get("condition", ""))
        if _eval_condition_expr(cond, trend_flags):
            trend_score += float(rule.get("weight", 0.0))

    intraday_score = 0.0
    for rule in cfg.get("intraday", []):
        cond = str(rule.get("condition", ""))
        if _eval_condition_expr(cond, intraday_flags):
            intraday_score += float(rule.get("weight", 0.0))

    trigger_signal = "NONE"
    trigger_conf = 0.0
    for rule in cfg.get("trigger", []):
        cond = str(rule.get("condition", ""))
        if _eval_condition_expr(cond, trigger_flags):
            trigger_signal = str(rule.get("signal", "NONE"))
            trigger_conf = float(rule.get("confidence", 0.0))
            break

    trend_signal = "BULLISH" if trend_score > 0.2 else ("BEARISH" if trend_score < -0.2 else "NEUTRAL")
    intraday_signal = "UP" if intraday_score > 0.15 else ("DOWN" if intraday_score < -0.15 else "FLAT")

    if trend_signal == "BULLISH" and trigger_signal == "BUY" and intraday_signal == "UP":
        final_signal = "STRONG_BUY"
    elif trend_signal == "BULLISH" and trigger_signal == "BUY":
        final_signal = "BUY"
    elif trend_signal == "BEARISH" and trigger_signal == "SELL":
        final_signal = "SELL"
    else:
        final_signal = "NO_TRADE"

    confidence = max(0.0, min(1.0, (abs(trend_score) + abs(intraday_score) + trigger_conf) / 3.0))
    return {
        "trend_signal": trend_signal,
        "trend_score": round(trend_score, 3),
        "trigger_signal": trigger_signal,
        "trigger_confidence": round(trigger_conf, 3),
        "intraday_signal": intraday_signal,
        "intraday_score": round(intraday_score, 3),
        "final_signal": final_signal,
        "confidence": round(confidence, 3),
        "flags": {
            **trend_flags,
            **trigger_flags,
            **intraday_flags,
        },
    }


def _market_past_from_engine(target_day: datetime.date, transit_chart: dict, birth_chart: Optional[dict]) -> dict:
    logic = (ENGINE_CONFIG.get("market_past", {}) or {}).get("logic", []) or []
    tph = transit_chart.get("planet_houses", {}) if isinstance(transit_chart, dict) else {}
    dasha_lord = "Unknown"
    if birth_chart:
        for seq in birth_chart.get("dasha_sequences", []) or []:
            try:
                if seq["start"].date() <= target_day <= seq["end"].date():
                    dasha_lord = str(seq.get("lord", "Unknown"))
                    break
            except Exception:
                continue

    flags = {
        "jupiter_period": dasha_lord == "Jupiter",
        "2_11_active": tph.get("Jupiter") in {2, 11} or tph.get("Rahu") in {2, 11},
        "saturn_period": dasha_lord == "Saturn",
        "8_12_active": tph.get("Saturn") in {8, 12},
        "rahu_period": dasha_lord == "Rahu",
    }

    hits = []
    for rule in logic:
        if _eval_condition_expr(str(rule.get("condition", "")), flags):
            hits.append(str(rule.get("result", "")))

    label = "VOLATILE" if "high_volatility_phase" in hits else (
        "BULL" if "historical_bull_phase" in hits else (
            "BEAR" if "historical_bear_phase" in hits else "MIXED"
        )
    )
    return {
        "dasha_lord": dasha_lord,
        "phase_label": label,
        "matched_logic": hits,
        "flags": flags,
    }


def _investment_advice_from_engine(birth_chart: Optional[dict], transit_chart: dict) -> dict:
    inv_cfg = ENGINE_CONFIG.get("investment_advice", {}) or {}
    janma_logic = inv_cfg.get("janma_kundli", []) or []
    gochar_logic = inv_cfg.get("gochar", []) or []
    commodity_map = inv_cfg.get("commodity_mapping", []) or []
    if not birth_chart:
        return {
            "action": "avoid",
            "invest_in": [],
            "avoid": ["high_leverage"],
            "reason": ["birth chart unavailable for janma strength analysis"],
            "janma_results": [],
            "gochar_results": [],
        }

    lagna = birth_chart.get("lagna", {})
    lagna_rashi = lagna.get("rashi", "Aries")
    ph = birth_chart.get("planet_houses", {})
    lord2 = _house_lord_for_number(lagna_rashi, 2)
    lord5 = _house_lord_for_number(lagna_rashi, 5)
    lord11 = _house_lord_for_number(lagna_rashi, 11)

    janma_flags = {
        "strong_2nd_11th_lords": _planet_is_strong(lord2, birth_chart) and _planet_is_strong(lord11, birth_chart),
        "5th_house_strong": _planet_is_strong(lord5, birth_chart) or ph.get("Jupiter") == 5,
        "mercury_strong": _planet_is_strong("Mercury", birth_chart),
        "8th_house_rahu": ph.get("Rahu") == 8,
    }

    tph = transit_chart.get("planet_houses", {}) if isinstance(transit_chart, dict) else {}
    gochar_flags = {
        "jupiter_transit_over_2_11": tph.get("Jupiter") in {2, 11},
        "saturn_afflicts_2_11": tph.get("Saturn") in {2, 11, 8, 12},
    }

    janma_results = []
    for rule in janma_logic:
        if _eval_condition_expr(str(rule.get("condition", "")), janma_flags):
            janma_results.append(str(rule.get("result", "")))

    gochar_results = []
    for rule in gochar_logic:
        if _eval_condition_expr(str(rule.get("condition", "")), gochar_flags):
            gochar_results.append(str(rule.get("result", "")))

    strong_planets = [p for p in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"] if _planet_is_strong(p, birth_chart)]
    invest_in = []
    for m in commodity_map:
        p = str(m.get("planet", "")).strip().title()
        if p in strong_planets:
            invest_in.extend([str(c) for c in (m.get("commodity", []) or [])])

    invest_in = list(dict.fromkeys(invest_in))[:8]
    high_risk = ("risk_high_sudden_gain_loss" in janma_results) or bool(janma_flags["8th_house_rahu"])
    growth_period = ("investment_growth_period" in gochar_results) or bool(gochar_flags["jupiter_transit_over_2_11"])
    protection = ("capital_protection_needed" in gochar_results) or bool(gochar_flags["saturn_afflicts_2_11"])

    reasons = []
    if "wealth_capability_high" in janma_results:
        reasons.append("2nd and 11th lords show stronger wealth capacity")
    if "trading_capability_high" in janma_results:
        reasons.append("5th house and Mercury support active trading decisions")
    if high_risk:
        reasons.append("Rahu influence on 8th indicates sudden gain-loss risk")
    if growth_period:
        reasons.append("Jupiter transit over wealth houses supports growth")
    if protection:
        reasons.append("Saturn pressure suggests capital protection discipline")

    if high_risk or protection:
        action = "avoid"
        avoid_list = ["high leverage", "speculative overexposure", "undisciplined intraday"]
    else:
        action = "invest_in"
        avoid_list = ["blind tips", "overtrading"]

    return {
        "action": action,
        "invest_in": invest_in,
        "avoid": avoid_list,
        "reason": reasons,
        "janma_results": janma_results,
        "gochar_results": gochar_results,
        "janma_flags": janma_flags,
        "gochar_flags": gochar_flags,
        "strong_planets": strong_planets,
    }


def _house_medical_profile(house_num: int, language: str = "hi") -> Dict[str, object]:
    house_map = {
        1: {
            "body_hi": "सिर, मस्तिष्क, चेहरा", "body_en": "head, brain, face",
            "issues_hi": ["सिर दर्द", "आधे सिर का दर्द", "मस्तिष्क विकार संकेत", "व्यक्तित्व असंतुलन"],
            "issues_en": ["headache", "migraine", "brain disorder tendency", "personality imbalance"],
        },
        2: {
            "body_hi": "आंखें, चेहरा, दांत, जीभ, गला", "body_en": "eyes, face, teeth, tongue, throat",
            "issues_hi": ["आंखों की समस्या", "दांत रोग", "वाणी दोष", "गले का संक्रमण"],
            "issues_en": ["eye issues", "dental issues", "speech disorder", "throat infection"],
        },
        3: {
            "body_hi": "कंधे, हाथ, बाजू, फेफड़े", "body_en": "shoulders, arms, hands, lungs",
            "issues_hi": ["सांस की समस्या", "दम रोग संकेत", "हाथ दर्द", "तंत्रिका दुर्बलता"],
            "issues_en": ["breathing issues", "asthma tendency", "arm pain", "nervous weakness"],
        },
        4: {
            "body_hi": "छाती, हृदय, फेफड़े", "body_en": "chest, heart, lungs",
            "issues_hi": ["हृदय तनाव", "छाती दर्द प्रवृत्ति", "मानसिक अवसाद", "फेफड़ों पर दबाव"],
            "issues_en": ["heart strain", "chest pain tendency", "emotional depression", "lung stress"],
        },
        5: {
            "body_hi": "ऊपरी पेट, यकृत, अग्न्याशय", "body_en": "upper abdomen, liver, pancreas",
            "issues_hi": ["पाचन समस्या", "अम्लता", "यकृत तनाव", "मधुमेह प्रवृत्ति"],
            "issues_en": ["digestion issues", "acidity", "liver stress", "diabetes tendency"],
        },
        6: {
            "body_hi": "आंत, नाभि क्षेत्र", "body_en": "intestines, navel area",
            "issues_hi": ["अल्सर", "संक्रमण प्रवृत्ति", "उदर रोग", "दीर्घकालिक रोग"],
            "issues_en": ["ulcers", "infection tendency", "stomach disease", "chronic illness"],
        },
        7: {
            "body_hi": "जननांग, गुर्दे", "body_en": "reproductive organs, kidneys",
            "issues_hi": ["गुर्दा तनाव", "यौन विकार संकेत", "मूत्र संबंधी समस्या"],
            "issues_en": ["kidney stress", "sexual disorder tendency", "urinary issues"],
        },
        8: {
            "body_hi": "गुप्त अंग, गुदा, बृहदान्त्र", "body_en": "private organs, anus, colon",
            "issues_hi": ["बवासीर", "भगन्दर प्रवृत्ति", "गुप्त रोग", "दीर्घकालिक जटिलताएं"],
            "issues_en": ["piles", "fistula tendency", "hidden diseases", "chronic complications"],
        },
        9: {
            "body_hi": "जांघ, कूल्हे", "body_en": "thighs, hips",
            "issues_hi": ["जांघ दर्द", "साइटिका संकेत", "चलने-फिरने की समस्या"],
            "issues_en": ["thigh pain", "sciatica tendency", "mobility issues"],
        },
        10: {
            "body_hi": "घुटने, जोड़", "body_en": "knees, joints",
            "issues_hi": ["गठिया प्रवृत्ति", "जोड़ दर्द", "जकड़न"],
            "issues_en": ["arthritis tendency", "joint pain", "stiffness"],
        },
        11: {
            "body_hi": "पिंडली, रक्त संचार", "body_en": "calves, blood circulation",
            "issues_hi": ["रक्त विकार संकेत", "ऐंठन", "रक्त संचार समस्या"],
            "issues_en": ["blood disorder tendency", "cramps", "circulation issues"],
        },
        12: {
            "body_hi": "पैर, बायीं आंख, निद्रा तंत्र", "body_en": "feet, left eye, sleep system",
            "issues_hi": ["अनिद्रा", "पैर दर्द", "बायीं आंख की कमजोरी", "अस्पताल-योग जोखिम काल"],
            "issues_en": ["insomnia", "foot pain", "left-eye weakness", "hospitalization risk windows"],
        },
    }

    data = house_map.get(int(house_num or 0), {
        "body_hi": "शरीर संतुलन", "body_en": "body balance",
        "issues_hi": ["सामान्य स्वास्थ्य निगरानी"], "issues_en": ["general health monitoring"],
    })

    hi = str(language or "hi").lower() == "hi"
    if hi:
        return {
            "body_parts": data["body_hi"],
            "possible_issues": data["issues_hi"],
        }
    return {
        "body_parts": data["body_en"],
        "possible_issues": data["issues_en"],
    }


def _health_risk_note(house_num: int, lord: str, occupants: List[str], language: str = "hi") -> str:
    hn = int(house_num or 0)
    occ = set([str(x).strip() for x in (occupants or []) if str(x).strip()])
    is_dusthana = hn in {6, 8, 12}
    saturn_hit = ("Saturn" in occ) or (str(lord).strip() == "Saturn")
    rahu_hit = ("Rahu" in occ) or (str(lord).strip() == "Rahu")

    if str(language or "hi").lower() == "hi":
        if is_dusthana and saturn_hit:
            return "यह दुष्टभाव और शनि का संयोजन दीर्घकालिक रोग प्रवृत्ति बढ़ा सकता है; नियमित जांच आवश्यक है।"
        if is_dusthana and rahu_hit:
            return "यह दुष्टभाव और राहु का संयोजन छिपे या असामान्य लक्षण दे सकता है; जांच में विलंब न करें।"
        if is_dusthana:
            return "यह दुष्टभाव अधिक स्वास्थ्य सतर्कता मांगता है; लक्षणों की उपेक्षा न करें।"
        return "लग्न-६-८-१२ अक्ष को साथ देखकर निवारक जीवनशैली रखना लाभकारी रहेगा।"

    if is_dusthana and saturn_hit:
        return "Dusthana + Saturn can indicate chronic health patterns; periodic monitoring is advised."
    if is_dusthana and rahu_hit:
        return "Dusthana + Rahu can show hidden/atypical symptoms; avoid delay in diagnosis."
    if is_dusthana:
        return "This Dusthana house requires higher health vigilance and early response to symptoms."
    return "Read this with the Lagna-6-8-12 axis and prioritize preventive health discipline."


def _product_market_symbols(product: str) -> List[str]:
    p = (product or "").strip().lower()
    mapping = {
        "gold": ["GC=F", "XAUUSD=X"],
        "silver": ["SI=F", "XAGUSD=X"],
        "crude oil": ["CL=F", "BZ=F"],
        "crude": ["CL=F", "BZ=F"],
        "natural gas": ["NG=F"],
        "copper": ["HG=F"],
        "aluminium": ["ALI=F"],
        "zinc": ["ZNC=F"],
        "soybean": ["ZS=F"],
        "wheat": ["ZW=F"],
        "sugar": ["SB=F"],
        "rice": ["ZR=F"],
        "nifty": ["^NSEI"],
        "bank nifty": ["^NSEBANK"],
        "banknifty": ["^NSEBANK"],
        "sensex": ["^BSESN"],
        "bitcoin": ["BTC-USD"],
    }

    for key, symbols in mapping.items():
        if key in p:
            return symbols

    # If user directly gives a known ticker-like value, try it as-is.
    if re.fullmatch(r"[A-Za-z0-9^=._-]{2,16}", product.strip()):
        return [product.strip().upper()]

    return []


def _price_unit_profile(product: str) -> dict:
    p = (product or "").strip().lower()

    # Unit assumptions are used only for human-readable display.
    if "gold" in p:
        return {"currency": "INR", "base_unit": "10g", "base_grams": 10.0}
    if "silver" in p:
        return {"currency": "INR", "base_unit": "kg", "base_grams": 1000.0}
    if any(x in p for x in ["wheat", "rice", "sugar", "soybean", "chana", "cotton"]):
        return {"currency": "INR", "base_unit": "quintal", "base_grams": 100000.0}
    if any(x in p for x in ["crude", "natural gas", "copper", "zinc", "aluminium"]):
        return {"currency": "INR", "base_unit": "unit", "base_grams": None}
    return {"currency": "INR", "base_unit": "unit", "base_grams": None}


def _price_breakdown_inr(close_rate: Optional[float], product: str) -> dict:
    profile = _price_unit_profile(product)
    if close_rate is None:
        return {
            "currency": profile.get("currency", "INR"),
            "base_unit": profile.get("base_unit", "unit"),
            "price": None,
            "per_gram": None,
            "per_kg": None,
            "per_quintal": None,
        }

    base_grams = profile.get("base_grams")
    price = float(close_rate)
    per_gram = None
    per_kg = None
    per_quintal = None

    if isinstance(base_grams, (int, float)) and base_grams > 0:
        per_gram = price / float(base_grams)
        per_kg = per_gram * 1000.0
        per_quintal = per_kg * 100.0

    return {
        "currency": profile.get("currency", "INR"),
        "base_unit": profile.get("base_unit", "unit"),
        "price": round(price, 4),
        "per_gram": round(per_gram, 4) if per_gram is not None else None,
        "per_kg": round(per_kg, 4) if per_kg is not None else None,
        "per_quintal": round(per_quintal, 4) if per_quintal is not None else None,
    }


async def _fetch_historical_close(product: str, target_day: datetime.date) -> Optional[dict]:
    symbols = _product_market_symbols(product)
    if not symbols:
        return None

    # Extend window to absorb non-trading days/holidays.
    start_ts = int(datetime.combine(target_day - timedelta(days=10), datetime.min.time()).timestamp())
    end_ts = int(datetime.combine(target_day + timedelta(days=2), datetime.min.time()).timestamp())

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for symbol in symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                resp = await client.get(url, params={
                    "period1": start_ts,
                    "period2": end_ts,
                    "interval": "1d",
                    "events": "history",
                }, headers={"User-Agent": "MedhaAI-Jyotish/1.0"})
                data = resp.json()
                result = ((data or {}).get("chart") or {}).get("result") or []
                if not result:
                    continue

                block = result[0]
                timestamps = block.get("timestamp") or []
                quotes = (((block.get("indicators") or {}).get("quote") or [{}])[0] or {})
                closes = quotes.get("close") or []
                if not timestamps or not closes:
                    continue

                points = []
                for ts, close in zip(timestamps, closes):
                    if close is None:
                        continue
                    day = datetime.utcfromtimestamp(int(ts)).date()
                    points.append((day, float(close)))

                if not points:
                    continue

                points.sort(key=lambda x: x[0])

                # Pick last available trading session <= target_day.
                idx = -1
                for i, (day, _) in enumerate(points):
                    if day <= target_day:
                        idx = i
                if idx < 0:
                    continue

                session_day, close_price = points[idx]
                prev_close = points[idx - 1][1] if idx > 0 else None

                return {
                    "symbol": symbol,
                    "session_date": session_day.strftime("%Y-%m-%d"),
                    "close": round(close_price, 4),
                    "prev_close": round(prev_close, 4) if prev_close is not None else None,
                }
            except Exception as market_err:
                print("MARKET DATA WARNING:", repr(market_err))
                continue

    return None


@app.post("/tezi-mandi")
async def tezi_mandi(
    payload: TeziMandiInput,
    _user: Optional[str] = Depends(require_user),
    _rl: None = Depends(rate_limit),
):
    product = str(payload.product or "").strip()
    if not product:
        return {"error": "Product/commodity ka naam dena zaroori hai."}

    target_date_raw = str(payload.target_date or "").strip()
    try:
        target_date = datetime.strptime(target_date_raw, "%Y-%m-%d")
    except Exception:
        return {"error": "Target date format YYYY-MM-DD hona chahiye."}

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    today_date = now_ist.date()
    target_day = target_date.date()
    is_market_closed_today = (now_ist.hour, now_ist.minute) >= (15, 30)
    is_historical = (target_day < today_date) or (target_day == today_date and is_market_closed_today)

    lat = payload.lat
    lng = payload.lng
    if (lat is None or lng is None) and payload.place:
        glat, glng = await _geocode_place(payload.place)
        lat = lat if lat is not None else glat
        lng = lng if lng is not None else glng

    # Market session reference time (IST style) for same-day transit reading.
    market_time = "09:15:00"
    analysis_date = target_date.strftime("%Y-%m-%d")

    try:
        transit_chart = _compute_vedic_chart(analysis_date, market_time, lat, lng)
    except Exception as e:
        return {"error": f"Transit calculation failed: {str(e)[:180]}"}

    natal_chart = None
    try:
        natal_chart = _compute_vedic_chart(payload.dob, payload.tob, lat, lng)
    except Exception:
        natal_chart = None

    engine_prediction = _market_prediction_from_engine(transit_chart, natal_chart)
    engine_investment = _investment_advice_from_engine(natal_chart, transit_chart)
    engine_past = _market_past_from_engine(target_day, transit_chart, natal_chart) if is_historical else None

    planets = transit_chart.get("planets", {})
    houses = transit_chart.get("planet_houses", {})
    karaka_planets = _product_karaka_planets(product)

    score = 0
    drivers: List[str] = []

    for p in karaka_planets:
        pdata = planets.get(p, {})
        hnum = houses.get(p)
        ps = _planet_strength_score(p, pdata, hnum)
        score += ps
        sign_name = pdata.get("rashi", "?")
        dignity = pdata.get("dignity", "neutral") or "neutral"
        drivers.append(f"{p} in house {hnum or '?'} ({sign_name}, {dignity}) => score {ps:+d}")

    # Weekday support (Parashari-style timing support)
    weekday_planets = ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"]
    day_lord = weekday_planets[target_date.weekday()]
    if day_lord in karaka_planets:
        score += 1
        drivers.append(f"Day-lord support: {day_lord} aligns with commodity karakas (+1)")

    # Natal resonance: if transit key planet repeats natal sign, add conviction.
    if natal_chart:
        natal_planets = natal_chart.get("planets", {})
        resonance_hits = 0
        for p in karaka_planets:
            t_sign = planets.get(p, {}).get("rashi")
            n_sign = natal_planets.get(p, {}).get("rashi")
            if t_sign and n_sign and t_sign == n_sign:
                resonance_hits += 1
        if resonance_hits:
            score += min(2, resonance_hits)
            drivers.append(f"Natal-transit resonance hits: {resonance_hits} (+{min(2, resonance_hits)})")

    drivers.append(
        "Engine confluence => "
        f"trend={engine_prediction.get('trend_signal')}, "
        f"trigger={engine_prediction.get('trigger_signal')}, "
        f"intraday={engine_prediction.get('intraday_signal')}, "
        f"final={engine_prediction.get('final_signal')}"
    )

    volatility = "Low"
    if "Rahu" in karaka_planets or "Mars" in karaka_planets:
        volatility = "Medium"
    if houses.get("Rahu") in {1, 8, 10, 11} or houses.get("Mars") in {1, 8, 10, 11}:
        volatility = "High"

    signal = str(engine_prediction.get("final_signal", "NO_TRADE"))
    trend_signal = str(engine_prediction.get("trend_signal", "NEUTRAL"))
    trigger_signal = str(engine_prediction.get("trigger_signal", "NONE"))
    intraday_signal = str(engine_prediction.get("intraday_signal", "FLAT"))

    if signal == "STRONG_BUY":
        short_hi = f"{product} mein majboot kharid (STRONG_BUY) ka sanket hai."
        short_en = f"Strong buy signal for {product}."
    elif signal == "BUY":
        short_hi = f"{product} mein kharid (BUY) ka sanket hai."
        short_en = f"Buy signal for {product}."
    elif signal == "SELL":
        short_hi = f"{product} mein bechne (SELL) ka sanket hai."
        short_en = f"Sell signal for {product}."
    else:
        short_hi = f"{product} mein abhi NO_TRADE ka sanket hai."
        short_en = f"No-trade signal for {product}."

    confidence = int(round(max(0.0, min(1.0, float(engine_prediction.get("confidence", 0.0)))) * 100))
    next_check = (target_date + timedelta(days=7)).strftime("%Y-%m-%d")

    # Probabilities for forecast mode: Up / Neutral / Down.
    if signal == "STRONG_BUY":
        up_prob = min(90, 62 + int(confidence * 0.25))
        down_prob = max(5, 18 - int(confidence * 0.08))
    elif signal == "BUY":
        up_prob = min(80, 52 + int(confidence * 0.2))
        down_prob = max(10, 26 - int(confidence * 0.1))
    elif signal == "SELL":
        down_prob = min(80, 52 + int(confidence * 0.2))
        up_prob = max(10, 26 - int(confidence * 0.1))
    else:
        up_prob = max(20, 30 - int(confidence * 0.05))
        down_prob = max(20, 30 - int(confidence * 0.05))

    neutral_prob = 100 - up_prob - down_prob
    if neutral_prob < 8:
        # Keep each bucket visible and meaningful.
        need = 8 - neutral_prob
        take_up = min(need // 2 + need % 2, max(0, up_prob - 8))
        up_prob -= take_up
        need -= take_up
        take_down = min(need, max(0, down_prob - 8))
        down_prob -= take_down
        neutral_prob = 100 - up_prob - down_prob

    up_prob = int(round(up_prob))
    down_prob = int(round(down_prob))
    neutral_prob = int(100 - up_prob - down_prob)

    strongest_side = "up" if up_prob >= neutral_prob and up_prob >= down_prob else (
        "down" if down_prob >= up_prob and down_prob >= neutral_prob else "neutral"
    )

    hi_lang = (str(payload.language or "hi").lower() == "hi")
    vol_hi_map = {"Low": "Kam", "Medium": "Madhyam", "High": "Ucch"}
    display_signal_hi_map = {
        "STRONG_BUY": "Majboot Kharid (Strong Buy)",
        "BUY": "Kharid (Buy)",
        "SELL": "Bikri (Sell)",
        "NO_TRADE": "No Trade",
    }
    display_signal_en_map = {
        "STRONG_BUY": "Strong Buy",
        "BUY": "Buy",
        "SELL": "Sell",
        "NO_TRADE": "No Trade",
    }
    display_signal_hi = display_signal_hi_map.get(signal, signal)
    display_signal_en = display_signal_en_map.get(signal, signal)

    inv_action = str(engine_investment.get("action", "avoid"))
    inv_list = [str(x) for x in (engine_investment.get("invest_in", []) or []) if str(x).strip()]
    inv_reasons = [str(x) for x in (engine_investment.get("reason", []) or []) if str(x).strip()]

    if hi_lang:
        if inv_action == "invest_in":
            sectors = ", ".join(inv_list[:5]) if inv_list else "selected sectors"
            why = " ; ".join(inv_reasons[:3]) if inv_reasons else "janma-gochar support is positive"
            investment_advice = f"निवेश का संकेत है। प्रमुख सेक्टर: {sectors}. कारण: {why}."
        else:
            why = " ; ".join(inv_reasons[:3]) if inv_reasons else "risk protection signals are active"
            investment_advice = f"आक्रामक पोजिशन से बचें। कारण: {why}."
    else:
        if inv_action == "invest_in":
            sectors = ", ".join(inv_list[:5]) if inv_list else "selected sectors"
            why = " ; ".join(inv_reasons[:3]) if inv_reasons else "janma-gochar support is positive"
            investment_advice = f"Invest signal. Focus sectors: {sectors}. Reason: {why}."
        else:
            why = " ; ".join(inv_reasons[:3]) if inv_reasons else "risk protection signals are active"
            investment_advice = f"Avoid aggressive exposure. Reason: {why}."

    if is_historical:
        market_ref = await _fetch_historical_close(product, target_day)
        close_rate = market_ref.get("close") if market_ref else None
        ref_day = market_ref.get("session_date") if market_ref else target_day.strftime("%Y-%m-%d")
        prev_close = market_ref.get("prev_close") if market_ref else None
        phase_label = str((engine_past or {}).get("phase_label", "MIXED"))
        price_breakdown = _price_breakdown_inr(close_rate, product)

        change_pct = None
        change_abs = None
        market_direction = "volatile" if phase_label == "VOLATILE" else (
            "up" if phase_label == "BULL" else ("down" if phase_label == "BEAR" else "neutral")
        )
        if close_rate is not None and prev_close not in (None, 0):
            change_abs = close_rate - prev_close
            change_pct = (change_abs / prev_close) * 100.0
            if abs(change_pct) < 0.2:
                market_direction = "neutral"
            elif change_pct > 0:
                market_direction = "up"
            else:
                market_direction = "down"

        if hi_lang:
            if close_rate is not None:
                requested_str = target_day.strftime('%d-%m-%Y')
                session_str = datetime.strptime(ref_day, '%Y-%m-%d').strftime('%d-%m-%Y')
                date_note = (
                    f"{requested_str} (market holiday/non-trading day), isliye nearest traded session {session_str} liya gaya. "
                    if session_str != requested_str else
                    f"{requested_str} ko "
                )
                if market_direction == "up":
                    movement_line = f"us din {abs(change_pct or 0):.2f}% upar band hua."
                elif market_direction == "down":
                    movement_line = f"us din {abs(change_pct or 0):.2f}% neeche band hua."
                else:
                    movement_line = "us din bazaar neutral (sthir) raha."
                unit_line = (
                    f"Closing figure: Rs {close_rate:.2f} per {price_breakdown.get('base_unit')}. "
                    f"Approx: Rs {price_breakdown.get('per_gram'):.2f}/gram, "
                    f"Rs {price_breakdown.get('per_kg'):.2f}/kg, "
                    f"Rs {price_breakdown.get('per_quintal'):.2f}/quintal."
                    if price_breakdown.get("per_gram") is not None else
                    f"Closing figure: Rs {close_rate:.2f} per {price_breakdown.get('base_unit')}."
                )
                summary = (
                    f"{date_note}{product} ka closing rate {close_rate:.2f} tha, {movement_line} {unit_line} Past phase label: {phase_label}."
                )
            else:
                summary = (
                    f"{target_day.strftime('%d-%m-%Y')} ke liye {product} ka exact closing rate source se nahi mil paya. "
                    f"Astro signal: {display_signal_hi}. Past phase label: {phase_label}."
                )
        else:
            if close_rate is not None:
                requested_str = target_day.strftime('%Y-%m-%d')
                session_str = ref_day
                date_note = (
                    f"Requested date {requested_str} was a non-trading day, so nearest traded session {session_str} was used. "
                    if session_str != requested_str else
                    f"On {requested_str}, "
                )
                if market_direction == "up":
                    movement_line = f"closed {abs(change_pct or 0):.2f}% up on that session."
                elif market_direction == "down":
                    movement_line = f"closed {abs(change_pct or 0):.2f}% down on that session."
                else:
                    movement_line = "closed neutral (sideways) on that session."
                unit_line = (
                    f"Closing figure: Rs {close_rate:.2f} per {price_breakdown.get('base_unit')}. "
                    f"Approx: Rs {price_breakdown.get('per_gram'):.2f}/gram, "
                    f"Rs {price_breakdown.get('per_kg'):.2f}/kg, "
                    f"Rs {price_breakdown.get('per_quintal'):.2f}/quintal."
                    if price_breakdown.get("per_gram") is not None else
                    f"Closing figure: Rs {close_rate:.2f} per {price_breakdown.get('base_unit')}."
                )
                summary = (
                    f"{date_note}{product} closing rate was {close_rate:.2f}; it {movement_line} {unit_line} Past phase label: {phase_label}."
                )
            else:
                summary = (
                    f"Exact historical close for {product} on {target_day.strftime('%Y-%m-%d')} could not be fetched. "
                    f"Astro signal: {display_signal_en}. Past phase label: {phase_label}."
                )
    else:
        price_breakdown = {
            "currency": "INR",
            "base_unit": _price_unit_profile(product).get("base_unit", "unit"),
            "price": None,
            "per_gram": None,
            "per_kg": None,
            "per_quintal": None,
        }
        summary = (
            f"{short_hi} Trend: {trend_signal}, Trigger: {trigger_signal}, Intraday: {intraday_signal}. Asthirta: {vol_hi_map.get(volatility, volatility)}. Vishwas star: {confidence}%. Agli samiksha: {next_check}."
            if hi_lang
            else f"{short_en} Trend: {trend_signal}, Trigger: {trigger_signal}, Intraday: {intraday_signal}. Volatility: {volatility}. Confidence: {confidence}%. Next review: {next_check}."
        )

    if not is_historical:
        if hi_lang:
            strongest_line = (
                f"Up jane ke {up_prob}% chances, Neutral ke {neutral_prob}% chances, Down ke {down_prob}% chances. "
                f"Sabse mazboot sambhavana: {'Up' if strongest_side == 'up' else ('Down' if strongest_side == 'down' else 'Neutral')}."
            )
        else:
            strongest_line = (
                f"Up chances: {up_prob}%, Neutral chances: {neutral_prob}%, Down chances: {down_prob}%. "
                f"Strongest probability: {strongest_side}."
            )
        summary = f"{summary} {strongest_line}"

    return {
        "product": product,
        "target_date": analysis_date,
        "mode": "historical" if is_historical else "forecast",
        "signal": signal,
        "display_signal_hi": display_signal_hi,
        "display_signal_en": display_signal_en,
        "summary": summary,
        "investment_advice": investment_advice,
        "confidence": confidence,
        "chance_up_percent": up_prob,
        "chance_neutral_percent": neutral_prob,
        "chance_down_percent": down_prob,
        "strongest_probability_side": strongest_side,
        "historical_close_rate": close_rate if is_historical else None,
        "historical_prev_close_rate": prev_close if is_historical else None,
        "historical_change_percent": round(change_pct, 4) if is_historical and change_pct is not None else None,
        "historical_change_value": round(change_abs, 4) if is_historical and change_abs is not None else None,
        "historical_market_direction": market_direction if is_historical else None,
        "historical_phase_label": (engine_past or {}).get("phase_label") if is_historical else None,
        "historical_session_date": ref_day if is_historical else None,
        "price_currency": price_breakdown.get("currency"),
        "price_base_unit": price_breakdown.get("base_unit"),
        "price_per_base_unit": price_breakdown.get("price"),
        "price_per_gram": price_breakdown.get("per_gram"),
        "price_per_kg": price_breakdown.get("per_kg"),
        "price_per_quintal": price_breakdown.get("per_quintal"),
        "volatility": volatility,
        "method": "Engine Config Multi-Layer Market Framework v4",
        "drivers": drivers,
        "market_prediction": engine_prediction,
        "market_past": engine_past,
        "investment_advice_engine": engine_investment,
        "next_check_date": None if is_historical else next_check,
    }


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "openai_configured": openai_client is not None,
        "gemini_configured": model is not None,
        "llm_available": (openai_client is not None) or (model is not None),
    }

@app.post("/full-analysis")
async def full_analysis(
    user: UserInput,
    _user: Optional[str] = Depends(require_user),
    _rl: None = Depends(rate_limit),
):
    if model is None and openai_client is None:
        return {
            "prediction": "Backend chal raha hai, lekin koi LLM key (OPENAI_API_KEY ya GOOGLE_API_KEY) set nahi hai. backend/.env check karein."
        }

    # Geocode if lat/lng not provided by frontend
    if (user.lat is None or user.lng is None) and user.place:
        _geo_lat, _geo_lng = await _geocode_place(user.place)
        if _geo_lat is not None:
            user = user.model_copy(update={"lat": _geo_lat, "lng": _geo_lng})

    # â”€â”€ Compute real birth chart â”€â”€
    chart_text = ""
    dasha_maha = "?"
    dasha_antar = "?"
    try:
        chart = _compute_vedic_chart(user.dob, user.tob, user.lat, user.lng)
        chart_text = _chart_to_prompt_text(chart, user.language)
        dasha_maha = chart["dasha"].get("mahadasha", "?")
        dasha_antar = chart["dasha"].get("antardasha", "?")
    except Exception as chart_err:
        chart_text = f"\n[Chart computation note: {str(chart_err)[:200]}]\n"

    lang_word = "Hindi" if user.language == "hi" else "English"
    hi = (user.language == "hi")

    if hi:
        prompt = f"""Aap Fortune Guru hain â€” ek anubhavi Vedic jyotishi jiske paas 30+ saal ka gyan hai.

JATAK KI JAANKARI:
Naam: {user.first_name} | Janm: {user.dob} | Samay: {user.tob} | Sthan: {user.place}
Bhagya Ank: {user.selected_number}
{chart_text}

NIRDESH â€” BAHUT ZAROORI:
1. Upar diye gaye WAASTAVIK graha stithi (Swiss Ephemeris computed) ka upyog karein.
2. Har ek prediction mein SPECIFIC graha, bhava, nakshatra, ya dasha ka NAAM lein aur samjhayen ki kyun yeh prediction sach hai.
   Udaharan: "Shani 10ve bhave mein Makar rashi mein swakshetra mein hai, isliye career mein discipline aur mehnat se safalta milti hai..."
3. Dasha kaal ke hisaab se timing batayein â€” agle 90 din mein kaun sa graha kya karega.
4. Koi bhi generic ya copy-paste jaisi baat mat likhein. Har line is kundli ke liye unique ho.
5. Ucha/Neech/Swakshetra grahas ka vishesh prabhav batayein.
6. Khud ko kabhi AI/model/assistant na bolen. Hamesha apne liye sirf "Guru Ji" shabd ka upyog karein.
7. Past-Present-Future (Ateet-Vartaman-Bhavishya) teeno ka ullekh karein, aur har phase ke saath samay-avadhi likhein.
8. Relative/family, dost-mitra, workplace atmosphere, aur samajik parisar par prabhav ko alag se mention karein.
9. Bhasha Vedic Rishi-vani jaisi ho: aisa lage jaise grah swayam sanket de rahe hon, lekin facts chart-based hi hon.
10. Har mukhya section ki shuruaat 1 engaging "Divya Sanket" line se karein jo user ko emotionally connected rakhe.
11. Har section ke ant me 1 "Agla Karm Sankalp" line dein jisse user actionable aur hopeful rahe.

RESPONSE FORMAT (Hindi mein, headings bold rakhein):

**1. Lagna aur Vyaktitva** (Lagna rashi, nakshatra aur lagnesh ke aadhar par â€” 4 specific points)

**2. Chandra Rashi aur Mana** (Moon ki rashi, nakshatra, bhava se emotional nature â€” 3-4 points)

**3. Career aur Arth** (2nd, 10th, 6th bhava ke grahas ke naam lekar â€” 4-5 specific points)

**4. Prem, Vivah aur Rishte** (5th aur 7th bhava ke lord/grahas ke naam lekar â€” 3-4 points)

**5. Swasthya** (6th, 8th bhava aur unme baithe grahas ke aadhar par â€” 3 points)

**6. {dasha_maha} Mahadasha â€” {dasha_antar} Antardasha: Agle 90 Din** (Is dasha ke swabhav aur is kundli ke saath uska prabhav â€” 4-5 points, dates ke sath)

**7. Chart-Aadharit 5 Upay** (Har upay mein batayein ki kaunse graha ke liye hai aur kyun)

**8. Sthiti aur Savdhani** (Neech/peedit grahas ya adverse yogas ke aadhar par â€” 3 points)

Kul: 750-1000 shabd. Har line factual aur chart se justified ho."""
    else:
        prompt = f"""You are Fortune Guru — an expert Vedic astrologer with 30+ years of experience.

BIRTH DATA:
Name: {user.first_name} | DOB: {user.dob} | Time: {user.tob} | Place: {user.place}
Lucky Number: {user.selected_number}
{chart_text}

MANDATORY RULES:
1. Use the REAL planetary positions from the HOUSE OCCUPANCY TABLE above (Swiss Ephemeris, Lahiri ayanamsa).
2. Do NOT place any planet in a house unless it is listed there in the table. If House 1 has only Sun, only Sun is there.
3. Every single prediction MUST name the exact planet, house, nakshatra, or dasha it is based on.
   Example: "Jupiter in 9th house in Cancer (exalted) activates higher learning and spiritual fortune..."
4. Time events to the current dasha period: {dasha_maha} Mahadasha - {dasha_antar} Antardasha.
5. Nothing generic. Every line must be unique to this specific chart.
6. Call out Ucha/Neech/Swakshetra planet effects explicitly.
7. Never refer to yourself as AI/model/assistant. Use only "Guru Ji" as self-reference.
8. Explicitly cover Past, Present, and Future phases with clear time windows.
9. Include effects on relatives/family, friends/network, workplace atmosphere, and social environment.
10. Tone should feel like Vedic Rishi-vani, as if planets are speaking their message, while staying chart-grounded.
11. Open each section with one engaging "Divine Signal" line and close with one "Next Dharma Action" line.

RESPONSE FORMAT (bold headings):

**1. Lagna & Personality** (From Lagna sign, nakshatra, Lagna lord â€” 4 specific points)

**2. Moon Sign & Emotional Nature** (Moon rashi, nakshatra, house â€” 3-4 points)

**3. Career & Wealth** (Name actual 2nd, 10th, 6th house planets â€” 4-5 specific points)

**4. Love, Marriage & Relationships** (Name 5th and 7th house lords/planets â€” 3-4 points)

**5. Health** (Based on 6th, 8th house planets â€” 3 points)

**6. {dasha_maha} Mahadasha â€” {dasha_antar} Antardasha: Next 90 Days** (This dasha's nature + its effect on THIS chart â€” 4-5 points with timing)

**7. Chart-Based 5 Remedies** (Each remedy must state which planet it's for and why)

**8. Cautions** (Based on debilitated/afflicted planets or adverse yogas â€” 3 points)

Total: 750-1000 words. Every line must be factually tied to the chart above."""

    try:
        response = await generate_content_with_timeout(prompt)
        text = getattr(response, "text", "").strip() or "Prediction generate nahi hua."
        text = _normalize_self_reference(text)
        return {"prediction": text}
    except asyncio.TimeoutError:
        return {
            "prediction": (
                f"Prediction service timeout ({int(MODEL_TIMEOUT_SECONDS)}s). "
                "Kripya dubara try karein."
            )
        }
    except Exception as e:
        print("BACKEND ERROR:", repr(e))
        err_text = str(e).lower()
        if "resourceexhausted" in err_text or "quota" in err_text:
            return {
                "prediction": (
                    "Dasha detailed response abhi quota limit ki wajah se seedha nahi aa pa raha. "
                    "Kripya thodi der baad retry karein; tab tak chart ke Janam/Gochar/Prashna sections se actionable guidance follow karein."
                )
            }
        if "timeout" in err_text:
            return {
                "prediction": (
                    "Dasha detailed response is samay delay ho raha hai (timeout). "
                    "Kripya dubara try karein; agle attempt me detailed output milega."
                )
            }
        return {
            "prediction": (
                "Dasha detailed response temporary issue ke karan abhi available nahi hai. "
                "Kripya dobara try karein."
            )
        }


@app.post("/section-qa")
async def section_qa(
    payload: SectionQAInput,
    _user: Optional[str] = Depends(require_user),
    _rl: None = Depends(rate_limit),
):
    if model is None and openai_client is None:
        return {
            "answer": "Backend chal raha hai, lekin koi LLM key (OPENAI_API_KEY ya GOOGLE_API_KEY) set nahi hai. backend/.env check karein."
        }

    question = str(payload.question or "").strip()
    if not question:
        return {"answer": "Kripya apna question likhein."}

    question = question[:800]
    section = str(payload.section or "General").strip()[:80]
    language = str(payload.language or "hi").strip().lower()
    question_style = _detect_question_style(question, language)
    style_lock = _style_instruction(question_style)
    context_text = str(payload.context or "").strip()
    context_text = context_text[:6000]
    hi_lang = (language == "hi")
    answer_mode = str(payload.answer_mode or "short").strip().lower()
    is_detailed = answer_mode in {"detailed", "detail", "long", "full"}
    now = datetime.now()
    current_year = now.year
    current_date = now.strftime("%Y-%m-%d")

    if is_detailed:
        response_shape = (
            "DETAILED MODE OUTPUT FORMAT:\n"
            "- First line: 'Divya Sanket' (1 line).\n"
            "- Then 8-12 bullet points with exact ग्रह + house references.\n"
            "- Include Past/Present/Future sections and timing windows.\n"
            "- End with one 'Agla Karm Sankalp' line.\n"
            "- Length: 260-420 words."
        )
    else:
        response_shape = (
            "SHORT MODE OUTPUT FORMAT (DEFAULT):\n"
            "- Line 1: Direct verdict only: 'Hoga', 'Deri se hoga', or 'Abhi mushkil'.\n"
            "- Line 2: Timing (month window / antardasha end).\n"
            "- Line 3-4: Max 2 chart reasons (planet + house).\n"
            "- Line 5: One practical upay.\n"
            "- Total length: 70-120 words only. No long essay."
        )

    prompt = (
        f"You are Fortune Guru — an expert Vedic astrologer doing PRASHNA JYOTISH (horary astrology).\n"
        f"Today date is {current_date}. Current year is {current_year}.\n"
        f"The person's BIRTH CHART (from Swiss Ephemeris — use this as ground truth):\n"
        f"{context_text}\n\n"
        f"USER QUESTION: {question}\n\n"
        f"Requested answer mode: {'DETAILED' if is_detailed else 'SHORT (DEFAULT)'}\n\n"
        f"ANALYSIS STEPS — follow ALL of them:\n"
        f"\n"
        f"Step 1 — Identify RELEVANT BHAVA(S) for this question type:\n"
        f"  Travel nearby/short: 3rd Bhava | Long distance / foreign travel: 9th, 12th Bhava\n"
        f"  Career/job/profession: 10th, 6th, 2nd Bhava | Wealth/money/income: 2nd, 11th Bhava\n"
        f"  Marriage/life partner: 7th Bhava | Love/romance/children: 5th Bhava\n"
        f"  Health/body/disease: 1st, 6th, 8th Bhava | Land/property/home: 4th Bhava\n"
        f"  Spiritual/foreign settlement: 12th, 9th Bhava | Legal/competition: 6th Bhava\n"
        f"\n"
        f"Step 2 — Analyze the chart FOR THOSE SPECIFIC BHAVAS (from context above):\n"
        f"  - What sign is in that bhava? Who is the bhava lord?\n"
        f"  - Where (which house) does the bhava lord sit?\n"
        f"  - What planets are in that bhava? What is their dignity?\n"
        f"  - Is the bhava lord strong, weak, exalted, or debilitated?\n"
        f"\n"
        f"Step 3 — Connect to CURRENT DASHA (dasha data IS in the context — use it):\n"
        f"  - What house does the Mahadasha lord occupy?\n"
        f"  - Is the Antardasha lord connected to the relevant bhava?\n"
        f"  - When does the current antardasha end? What comes next?\n"
        f"\n"
        f"Step 4 — Give a CONCRETE ANSWER:\n"
        f"  - YES / NO / Yes but with delay — be direct\n"
        f"  - Specific TIMING: 'Under [Planet] Antardasha (ending [month year])...'\n"
        f"  - 2-3 clear chart reasons (cite exact planet + house number)\n"
        f"  - 1-2 Vedic remedies to strengthen the positive outcome\n"
        f"\n"
        f"STRICT RULES:\n"
        f"1. NEVER say 'dasha information not available' — dasha IS in the context. Use it.\n"
        f"2. NEVER say 'information not available' or 'I cannot determine' — analyze what is available.\n"
        f"3. Always give a DIRECT, SPECIFIC answer with timing. Not vague generalities.\n"
        f"4. Name specific planets and house numbers in every point.\n"
        f"5. Do not mention old past years as future prediction. Use {current_year} onward for future timelines.\n"
        f"6. If exact year is uncertain, use relative time windows (e.g., agle 3-6 mahine).\n"
        f"7. {style_lock}\n"
        f"8. Never refer to yourself as AI/model/assistant. Use only 'Guru Ji' as self-reference.\n"
        f"9. Keep tone like Vedic Rishi-vani; make it feel like grahas are delivering the guidance.\n"
        f"10. Follow requested output mode strictly.\n\n"
        f"{response_shape}\n"
    )

    try:
        response = await generate_content_with_timeout(prompt)
        text = getattr(response, "text", "").strip() or "Answer generate nahi hua."
        text = _normalize_self_reference(text)

        if text and not _answer_matches_style(text, question_style):
            rewrite_prompt = (
                "Rewrite the following answer in the exact requested language style. "
                "Do not change meaning, astrology facts, timing, or remedies.\n"
                f"Requested style: {style_lock}\n"
                "Original answer:\n"
                f"{text}"
            )
            try:
                rewrite = await generate_content_with_timeout(rewrite_prompt, timeout_seconds=25)
                rewritten_text = _normalize_self_reference(getattr(rewrite, "text", "").strip())
                if rewritten_text and _answer_matches_style(rewritten_text, question_style):
                    text = rewritten_text
            except Exception:
                pass

        return {"answer": text, "response_style": question_style}
    except asyncio.TimeoutError:
        return {
            "answer": (
                f"Q&A service timeout ({int(MODEL_TIMEOUT_SECONDS)}s). "
                "Kripya dubara try karein."
            ),
            "response_style": question_style,
        }
    except Exception as e:
        print("SECTION QA ERROR:", repr(e))
        err_text = str(e).lower()
        if "resourceexhausted" in err_text or "quota" in err_text:
            answer = "Q&A temporary unavailable due to API quota limit. Please retry after some time."
        elif "timeout" in err_text:
            answer = "Q&A response timed out. Please retry once."
        else:
            answer = "Q&A temporary technical issue occurred. Please retry."
        return {"answer": answer, "response_style": question_style}


def _repair_json(text: str) -> str:
    """Fix common model hallucinations that corrupt JSON keys."""
    # e.g. {"house ì‚¬ì‹¤ 7, -> {"house": 7,
    text = re.sub(r'"house\s+[^"\d]*?(\d+)\s*,', r'"house": \1,', text)
    # Remove stray non-ASCII garbage inside string keys
    text = re.sub(r'"([^"]{0,30})[^\x00-\x7F]+([^"]{0,30})"\s*:', r'"\1\2":', text)
    return text


def _normalize_self_reference(value):
    """Force one assistant name in all user-visible outputs."""
    if isinstance(value, dict):
        return {k: _normalize_self_reference(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_self_reference(v) for v in value]
    if isinstance(value, str):
        text = value
        patterns = [
            r"\bAI\b",
            r"\bassistant\b",
            r"\bmodel\b",
            r"\bacharya\s*ji\b",
            r"\bacharya\b",
            r"\bpandit\s*ji\b",
            r"\bpandit\b",
            r"\bguru\s*ji\b",
            r"\bguruji\b",
        ]
        for pat in patterns:
            text = re.sub(pat, "Guru Ji", text, flags=re.IGNORECASE)
        return text
    return value


def _contains_latin_chars(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", str(text or "")))


def _kundli_payload_has_hinglish(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False

    blocks = [
        payload.get("janam_kundli", {}),
        payload.get("gochar_kundli", {}),
        payload.get("prashna_kundli", {}),
    ]

    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ("prediction", "detailed_prediction"):
            if _contains_latin_chars(block.get(key, "")):
                return True

        steps = block.get("next_steps", [])
        if isinstance(steps, list):
            for s in steps:
                if _contains_latin_chars(s):
                    return True

        houses = block.get("houses", [])
        if isinstance(houses, list):
            for h in houses:
                if not isinstance(h, dict):
                    continue
                for hk in ("prediction", "advice", "upay", "body_parts", "health_note"):
                    if _contains_latin_chars(h.get(hk, "")):
                        return True
                issues = h.get("possible_issues", [])
                if isinstance(issues, list):
                    for issue in issues:
                        if _contains_latin_chars(issue):
                            return True

    return False


def _extract_json_block(text: str):
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    raw = match.group(0)
    # First try as-is
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try after repairing common model corruptions
    try:
        return json.loads(_repair_json(raw))
    except json.JSONDecodeError:
        return None


@app.post("/kundli-analysis")
async def kundli_analysis(
    user: UserInput,
    _user: Optional[str] = Depends(require_user),
    _rl: None = Depends(rate_limit),
):
    if model is None and openai_client is None:
        return {
            "error": "Backend chal raha hai, lekin koi LLM key (OPENAI_API_KEY ya GOOGLE_API_KEY) set nahi hai. backend/.env check karein."
        }

    # Geocode if lat/lng not provided by frontend
    if (user.lat is None or user.lng is None) and user.place:
        _geo_lat, _geo_lng = await _geocode_place(user.place)
        if _geo_lat is not None:
            user = user.model_copy(update={"lat": _geo_lat, "lng": _geo_lng})

    # â”€â”€ Compute real birth chart â”€â”€
    chart: Optional[dict] = None
    chart_text = ""
    dasha_by_decade: dict = {}
    chart_dasha: dict = {}
    try:
        chart = _compute_vedic_chart(user.dob, user.tob, user.lat, user.lng)
        chart_text = _chart_to_prompt_text(chart, user.language)
        dasha_by_decade = chart.get("dasha_by_decade", {})
        chart_dasha = chart.get("dasha", {})
    except Exception as ce:
        chart_text = f"\n[Chart computation note: {str(ce)[:200]}]\n"

    # ── Derived chart artefacts used throughout this endpoint ──
    # Authoritative 12-house table (Swiss Ephemeris); empty if chart unavailable.
    computed_houses = _build_computed_houses(chart, user.language) if chart else []

    # Current dasha lords for prompt timing references.
    maha = str(chart_dasha.get("mahadasha", "?"))
    antar = str(chart_dasha.get("antardasha", "?"))

    # Transit ("gochar") chart computed for the present moment, so the
    # multi-system analysis can evaluate live transit flags.
    transit_chart: Optional[dict] = None
    try:
        _now = datetime.now()
        transit_chart = _compute_vedic_chart(
            _now.strftime("%Y-%m-%d"), _now.strftime("%H:%M"),
            user.lat, user.lng,
        )
    except Exception as te:
        print("TRANSIT CHART WARNING:", repr(te))
        transit_chart = None

    # Multi-system (Parashar → Jaimini → KP → Bhrigu) analyses per mode.
    multi_system_natal = _multi_system_analysis(chart, transit_chart, user.language, "", "natal") if chart else {}
    multi_system_gochar = _multi_system_analysis(chart, transit_chart, user.language, "", "gochar") if chart else {}
    multi_system_prashna = _multi_system_analysis(chart, transit_chart, user.language, "", "prashna") if chart else {}

    hi = (user.language == "hi")
    lang_instr = "Hindi (Devanagari)" if hi else "English"

    # Build decade context for prompt
    decade_ctx_lines = []
    for age_range, lords in dasha_by_decade.items():
        decade_ctx_lines.append(f"  Age {age_range}: {lords}")
    decade_ctx = "\n".join(decade_ctx_lines) or "  (Dasha timeline not computed)"

    def _fallback_house_advice(lord, language):
        en = {
            "Sun": "Cultivate confidence and integrity; honour your father and mentors.",
            "Moon": "Protect your peace of mind; keep a steady routine and nurture key relationships.",
            "Mars": "Channel energy into disciplined action; avoid haste, anger and conflict.",
            "Mercury": "Sharpen communication and study; be precise in business and contracts.",
            "Jupiter": "Stay disciplined and ethical; donate yellow items on Thursdays and respect teachers.",
            "Venus": "Keep relationships harmonious and avoid over-indulgence and excess comfort.",
            "Saturn": "Serve elders and workers; carry responsibility steadily and patiently.",
            "Rahu": "Avoid shortcuts; follow a clear plan with patience and discipline.",
            "Ketu": "Meditate regularly and avoid sudden detachment from your duties.",
        }
        hi_map = {
            "Sun": "आत्मविश्वास और सत्यनिष्ठा बढ़ाएँ; पिता और गुरुजनों का सम्मान करें।",
            "Moon": "मन की शांति बनाए रखें; नियमित दिनचर्या रखें और संबंधों का पोषण करें।",
            "Mars": "ऊर्जा को अनुशासित कर्म में लगाएँ; जल्दबाज़ी, क्रोध और विवाद से बचें।",
            "Mercury": "संवाद और अध्ययन को सशक्त करें; व्यापार और अनुबंध में स्पष्ट रहें।",
            "Jupiter": "गुरु अनुशासन अपनाएँ, गुरुवार को पीली वस्तु का दान करें।",
            "Venus": "संबंधों में मधुरता रखें और अतिविलास से बचें।",
            "Saturn": "बुजुर्ग और कर्मयोगियों की सेवा करें, जिम्मेदारी निरंतर निभाएँ।",
            "Rahu": "शॉर्टकट से बचें, स्पष्ट योजना और धैर्य अपनाएँ।",
            "Ketu": "नियमित ध्यान करें और अचानक विरक्ति से बचें।",
        }
        if language == "hi":
            return hi_map.get(lord, "नियमित साधना, सात्विक दिनचर्या और दान से लाभ मिलेगा।")
        return en.get(lord, "Stay disciplined, grounded, and continue practical remedies.")

    def _build_fallback_payload(reason: str) -> dict:
        is_hindi = user.language == "hi"
        planet_hi_names = {
            "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
            "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु",
        }

        def _planet_domain_text(planet: str) -> str:
            p = str(planet or "").strip()
            if is_hindi:
                p_hi = {
                    "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
                    "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु",
                }.get(p, p)
                mapping = {
                    "Sun": "नेतृत्व, अधिकार, आत्मविश्वास, प्रशासनिक दिशा",
                    "Moon": "मन, भावनाएँ, जनसंपर्क, पालन-पोषण",
                    "Mars": "साहस, क्रियाशीलता, सुरक्षा, संचालन",
                    "Mercury": "संवाद, व्यापार, विश्लेषण, लेखन, वाणिज्य",
                    "Jupiter": "ज्ञान, मार्गदर्शन, धर्म, वित्तीय विवेक",
                    "Venus": "सौंदर्य, कला, संबंध-संतुलन, सुविधा",
                    "Saturn": "अनुशासन, परिश्रम, व्यवस्था, दीर्घकालिक प्रयास",
                    "Rahu": "नवाचार, विदेश संबंध, असामान्य विस्तार",
                    "Ketu": "अनुसंधान, अध्यात्म, गहन अंतर्दृष्टि",
                }
                domain = mapping.get(p)
                if domain:
                    return f"{p_hi} से जुड़े क्षेत्र: {domain}"
                return f"{p_hi} से जुड़े प्रयासों में अनुशासित दृष्टि रखें"

            mapping = {
                "Sun": "leadership, authority, confidence, and public visibility",
                "Moon": "emotions, caregiving, audience connect, and adaptability",
                "Mars": "courage, engineering, operations, and decisive action",
                "Mercury": "communication, analytics, trade, writing, and sales",
                "Jupiter": "teaching, strategy, finance guidance, and wisdom",
                "Venus": "beauty, fashion, acting/media, arts, luxury, and relationships",
                "Saturn": "discipline, administration, systems, and persistence",
                "Rahu": "technology, foreign links, scale, and unconventional paths",
                "Ketu": "research, spirituality, depth, and inner clarity",
            }
            domain = mapping.get(p)
            if domain:
                return f"{p} domains: {domain}"
            return f"{p} themes require practical discipline and consistency"

        section_profiles = {
            "janam": {
                "label_hi": "जन्म दृष्टि",
                "label_en": "Natal Lens",
                "focus_hi": "मूल स्वभाव, जीवन-पथ और दीर्घकालिक व्यक्तित्व संतुलन",
                "focus_en": "core personality patterns and long-horizon life alignment",
                "tone_hi": "यह जन्म सूत्र आपके जीवन-पथ की मूल दिशा दर्शाता है",
                "tone_en": "this natal line reveals the foundational life direction",
                "house_angle_hi": "इस भाव से जीवन-भर के स्वभाविक पैटर्न और व्यक्तित्व स्थिरता समझी जाती है",
                "house_angle_en": "this house reveals lifelong personality and foundational patterns",
                "actions_hi": [
                    "दैनिक दिनचर्या को अनुशासित रखें।",
                    "परिवारिक संवाद में स्पष्टता और मर्यादा बनाए रखें।",
                    "साप्ताहिक अध्ययन और कौशल-वृद्धि का समय निश्चित करें।",
                    "दीर्घकालिक वित्तीय अनुशासन और बचत पर नियंत्रण रखें।",
                ],
                "actions_en": [
                    "Prioritize daily routine discipline first.",
                    "Keep family communication clear and respectful.",
                    "Fix a weekly learning block for skill compounding.",
                    "Track long-term finance discipline and savings ratio.",
                ],
            },
            "gochar": {
                "label_hi": "गोचर दृष्टि",
                "label_en": "Transit Lens",
                "focus_hi": "वर्तमान सक्रियता, समय-खिड़कियाँ और १२-१८ माह के परिवर्तन",
                "focus_en": "current activation windows and 12-18 month shifts",
                "tone_hi": "यह गोचर संकेत वर्तमान समय के चलायमान परिवर्तन दर्शाता है",
                "tone_en": "this transit signal reflects active timing shifts",
                "house_angle_hi": "इस भाव में वर्तमान समय-चक्र के तात्कालिक सक्रिय बिंदु दिखते हैं",
                "house_angle_en": "this house shows current-cycle short-term triggers",
                "actions_hi": [
                    "अगले ९० दिन के लक्ष्य चरणबद्ध मील-पत्थरों में बाँटें।",
                    "अवसर मिलने पर त्वरित कार्य करें, पर जोखिम नियंत्रण रखें।",
                    "कार्य-भार और विश्राम का संतुलन बनाए रखें।",
                    "उच्च अस्थिरता वाले निर्णयों में द्वितीय सत्यापन नियम अपनाएँ।",
                ],
                "actions_en": [
                    "Break the next 90-day goals into phased milestones.",
                    "Execute quickly on opportunities, but keep risk controlled.",
                    "Balance workload calendar with recovery cycles.",
                    "Follow a second-check rule for high-volatility decisions.",
                ],
            },
            "prashna": {
                "label_hi": "प्रश्न दृष्टि",
                "label_en": "Query Lens",
                "focus_hi": "तात्कालिक परिणाम, व्यावहारिक निर्णय और ३-९ माह के निष्कर्ष",
                "focus_en": "immediate outcomes and practical decisions for 3-9 months",
                "tone_hi": "यह प्रश्न दृष्टि तात्कालिक परिणामों की दिशा स्पष्ट करती है",
                "tone_en": "this query lens clarifies immediate result pathways",
                "house_angle_hi": "इस भाव से तत्काल निर्णयों का सीधा प्रभाव और परिणाम समझ आता है",
                "house_angle_en": "this house explains direct impact of immediate decisions",
                "actions_hi": [
                    "वर्तमान प्रश्न को तीन मापनीय कार्यों में विभाजित कर तुरंत आरंभ करें।",
                    "निर्णय-अवरोध से बचने हेतु समय-सीमा आधारित क्रियान्वयन रखें।",
                    "जोखिम-लाभ स्पष्ट हुए बिना बड़ा संकल्प न लें।",
                    "साप्ताहिक समीक्षा में प्रगति और बाधाएँ लिखकर पूर्ण करें।",
                ],
                "actions_en": [
                    "Break the current query into 3 measurable actions and start now.",
                    "Use deadline-based execution to avoid decision paralysis.",
                    "Avoid major commitments without clear risk-reward visibility.",
                    "Close each week with progress and blocker notes.",
                ],
            },
        }

        def _fallback_houses(section_key: str) -> List[dict]:
            houses = []
            profile = section_profiles.get(section_key, section_profiles["janam"])
            section_label = profile["label_hi"] if is_hindi else profile["label_en"]
            section_focus = profile["focus_hi"] if is_hindi else profile["focus_en"]
            section_angle = profile["house_angle_hi"] if is_hindi else profile["house_angle_en"]

            house_focus_hi = {
                1: "स्वभाव, स्वास्थ्य दिनचर्या और व्यक्तित्व छवि",
                2: "धन प्रवाह, वाणी अनुशासन और परिवारिक मूल्य",
                3: "संचार साहस, प्रयास लय और सहोदर समन्वय",
                4: "गृह-सुख, संपत्ति आराम और भावनात्मक स्थिरता",
                5: "बुद्धि, सृजनशीलता, शिक्षा और संतान संकेत",
                6: "सेवा, प्रतियोगिता, ऋण प्रबंधन और स्वास्थ्य सुधार",
                7: "साझेदारी विश्वास, दांपत्य संतुलन और सार्वजनिक व्यवहार",
                8: "अचानक परिवर्तन, शोध गहराई और गुप्त जोखिम नियंत्रण",
                9: "भाग्य, गुरु-कृपा, नीति और उच्च अध्ययन",
                10: "कर्म दिशा, अधिकार छवि और दृश्य कर्मफल",
                11: "लाभ नेटवर्क, आय स्रोत और लक्ष्य सिद्धि",
                12: "व्यय अनुशासन, विदेश संबंध और आध्यात्मिक पुनर्संतुलन",
            }
            house_focus_en = {
                1: "self-image, health rhythm, and personality stability",
                2: "cash flow, speech discipline, and family values",
                3: "communication courage, effort consistency, and coordination",
                4: "home comfort, property themes, and emotional grounding",
                5: "intelligence, creativity, education, and children themes",
                6: "service, competition, debt handling, and recovery",
                7: "partnership trust, marriage dynamics, and public dealing",
                8: "sudden changes, research depth, and hidden risk control",
                9: "fortune, mentorship, ethics, and higher learning",
                10: "career direction, authority image, and visible karma",
                11: "network gains, income channels, and target fulfillment",
                12: "expense discipline, foreign links, and spiritual reset",
            }

            for idx in range(1, 13):
                src = next((h for h in computed_houses if int(h.get("house", 0)) == idx), None)
                if src:
                    med = _house_medical_profile(idx, user.language)
                    # Unique prediction using computed data
                    occupants = src.get("occupants", []) or []
                    occ_str = ", ".join(occupants) if occupants else ("No planets" if not is_hindi else "कोई ग्रह नहीं")
                    lord = src.get("lord", "")
                    sign = src.get("sign", "")
                    analysis = src.get("analysis", "")
                    if is_hindi:
                        prediction = f"[{src.get('name', f'भाव {idx}')}]: राशि {src.get('sign_hi', '')}, भावेश {lord}, ग्रह: {occ_str}. {analysis}"
                    else:
                        prediction = f"[{src.get('name', f'House {idx}')}]: Sign {sign}, Lord {lord}, Planets: {occ_str}. {analysis}"
                    houses.append({
                        "house": idx,
                        "name": src.get("name", f"House {idx}"),
                        "sign": src.get("sign", ""),
                        "lord": src.get("lord", ""),
                        "analysis": src.get("analysis", ""),
                        "prediction": prediction,
                        "body_parts": med["body_parts"],
                        "possible_issues": med["possible_issues"],
                        "health_note": _health_risk_note(idx, lord, occupants, user.language),
                        "advice": _fallback_house_advice(str(lord), user.language),
                    })
                else:
                    med = _house_medical_profile(idx, user.language)
                    houses.append({
                        "house": idx,
                        "name": f"House {idx}",
                        "sign": "",
                        "lord": "",
                        "analysis": "Computed house data unavailable.",
                        "prediction": (
                            f"भाव {idx} का संक्षिप्त वैकल्पिक विश्लेषण प्रस्तुत है।"
                            if is_hindi else
                            f"A compact fallback reading is provided for House {idx}."
                        ),
                        "body_parts": med["body_parts"],
                        "possible_issues": med["possible_issues"],
                        "health_note": _health_risk_note(idx, "", [], user.language),
                        "advice": (
                            "दिनचर्या स्थिर रखें और सात्विक अनुशासन अपनाएँ।"
                            if is_hindi else
                            "Maintain a steady routine and practical discipline."
                        ),
                    })
            return houses

        def _fallback_block(section_key: str, section_name: str, horizon: str, include_decades: bool = False) -> dict:
            profile = section_profiles.get(section_key, section_profiles["janam"])
            focus = profile["focus_hi"] if is_hindi else profile["focus_en"]
            tone = profile["tone_hi"] if is_hindi else profile["tone_en"]
            system_map = {
                "janam": multi_system_natal,
                "gochar": multi_system_gochar,
                "prashna": multi_system_prashna,
            }
            sys_analysis = system_map.get(section_key, {})
            base_prediction = (
                f"{section_name} का सार ({horizon}): {tone}. "
                f"इस खंड का मूल केंद्र: {focus}."
                if is_hindi else
                f"{section_name} summary ({horizon}): {tone}. "
                f"Core section focus: {focus}."
            )

            if is_hindi:
                if section_key == "janam":
                    detailed_prediction = (
                        f"{section_name} का विस्तृत संकेत: यह जन्म दृष्टि आपके मूल स्वभाव, कर्म-धारा और दीर्घकालिक जीवन-दिशा को प्रकट करती है। "
                        f"अतीत चरण में आपने ऐसे अनुभव देखे होंगे जहाँ धैर्य, आत्मबल और संबंधों की परीक्षा साथ-साथ हुई। "
                        f"वर्तमान में नियमित दिनचर्या, संयमित वाणी और स्थिर निर्णय आपके लिए सुरक्षा कवच बन रहे हैं। "
                        f"परिवार, मित्र-मंडल और कार्यस्थल में सम्मान तब बढ़ेगा जब आप निरंतरता बनाए रखेंगे। "
                        f"ग्रह संकेत बताते हैं कि अनुशासित कर्म, वित्तीय संयम और भावनात्मक संतुलन से आपका मार्ग प्रशस्त होगा। "
                        f"स्वास्थ्य पक्ष में लग्न तथा ६-८-१२ अक्ष की सावधानी बनाए रखना आवश्यक रहेगा। "
                        f"आगामी चरण में पहचान की स्पष्टता, कर्म की नियमितता और संबंधों की मर्यादा आपके पक्ष को मजबूत करेगी। "
                        f"{horizon} अवधि में क्रमबद्ध प्रयास रखने पर प्रगति स्थिर और सार्थक रूप से बढ़ेगी।"
                    )
                elif section_key == "gochar":
                    detailed_prediction = (
                        f"{section_name} का विस्तृत संकेत: यह गोचर दृष्टि वर्तमान समय-चक्र की सक्रिय स्थितियों और अवसर-खिड़कियों को स्पष्ट करती है। "
                        f"अतीत की सुस्ती अब गति में बदल रही है, पर निर्णयों में जल्दबाजी से बचना आवश्यक है। "
                        f"वर्तमान चरण में अवसर और अस्थिरता साथ आएँगे, इसलिए जोखिम-जांच के साथ ही कदम बढ़ाएँ। "
                        f"कार्यस्थल पर दबाव बढ़ सकता है, किन्तु योजनाबद्ध कार्यशैली से लाभ मिलेगा। "
                        f"मित्र-वृत्त और नेटवर्क में विवेकपूर्ण सहयोग आपके लिए लाभकारी सिद्ध होगा। "
                        f"स्वास्थ्य दृष्टि से थकान, अनियमित दिनचर्या और तनाव पर शीघ्र नियंत्रण रखें। "
                        f"धन संबंधी निर्णय चरणबद्ध रखें और अनावश्यक जोखिम से दूरी बनाकर चलें। "
                        f"{horizon} अवधि में समयानुकूल कर्म और संतुलित दृष्टि से परिणाम स्थिर रूप से उन्नत होंगे।"
                    )
                else:
                    detailed_prediction = (
                        f"{section_name} का विस्तृत संकेत: यह प्रश्न दृष्टि तात्कालिक परिणाम, निर्णय-स्वच्छता और अगले महीनों की व्यावहारिक दिशा पर केंद्रित है। "
                        f"अतीत में विलंब या भ्रम ने गति को रोका होगा, पर अब स्पष्ट कार्यवाही आवश्यक है। "
                        f"वर्तमान में प्रश्न का उत्तर केवल सक्रिय कर्म में है; मापनीय कदम तुरंत आरंभ करें। "
                        f"परिवार और कार्यक्षेत्र दोनों में सीमित परंतु प्रभावी प्रतिबद्धताएँ अपनाना उचित रहेगा। "
                        f"ग्रह संकेत बताते हैं कि स्पष्ट संवाद, समय-सीमा और वित्तीय सावधानी यहाँ मुख्य भूमिका निभाएँगे। "
                        f"स्वास्थ्य पक्ष में तनाव और अनियमितता को तुरंत नियंत्रित करना हितकारी होगा। "
                        f"साप्ताहिक समीक्षा के साथ दो-तीन स्पष्ट लक्ष्य तय कर निरंतर पूर्ण करें। "
                        f"{horizon} अवधि में चरणबद्ध प्रयास और निर्णय अनुशासन से परिणाम शीघ्र और स्पष्ट मिलेंगे।"
                    )
            else:
                detailed_prediction = (
                    f"Detailed {section_name} fallback: viewed across past-present-future, the chart signals a workable growth trajectory. "
                    f"The past phase may have included delays that built practical maturity and clearer judgment. "
                    f"In the present, disciplined routines, better communication, and focused execution are likely to produce visible progress. "
                    f"Family interactions and workplace dynamics improve when responses remain calm and structured. "
                    f"For this section, emphasize {focus}; from a planetary-domain view, communication, finance discipline, relationship balance, and skills growth become key multipliers. "
                    f"Across the next {horizon}, phased planning, financial discipline, and spiritual grounding support stable advancement."
                )

            block = {
                "prediction": base_prediction,
                "detailed_prediction": detailed_prediction,
                "analysis_structure": str(sys_analysis.get("framework", "")),
                "analysis_meaning": str(sys_analysis.get("life_overview", "")),
                "analysis_timing": str(sys_analysis.get("event_timing", "")),
                "analysis_confirmation": str(sys_analysis.get("confirmation_notes", "")),
                "kp_core": sys_analysis.get("kp_core", {}),
                "next_steps": profile["actions_hi"] if is_hindi else profile["actions_en"],
                "houses": _fallback_houses(section_key),
            }
            if include_decades:
                block["decade_predictions"] = [
                    {
                        "age_range": age_range,
                        "dasha_lords": lords,
                        "predictions": [
                            (
                                f"Is dashak me {lords} ke anusaar career aur parivar me dhairya ke saath pragati milegi."
                                if is_hindi else
                                f"This decade under {lords} supports gradual progress in career and family themes."
                            ),
                            (
                                "Sthir nirnay long-term laabh ko mazboot karenge."
                                if is_hindi else
                                "Stable decisions will strengthen long-term gains."
                            ),
                            (
                                "Discipline aur Guru margdarshan is phase ka key factor rahega."
                                if is_hindi else
                                "Discipline and guidance remain key in this phase."
                            ),
                        ],
                    }
                    for age_range, lords in dasha_by_decade.items()
                ]
            return block

        chart_summary = {}
        if chart:
            lagna_raw = chart.get("lagna", {})
            planets_raw = chart.get("planets", {})
            ph_raw = chart.get("planet_houses", {})
            chart_summary = {
                "lagna": {
                    "rashi": lagna_raw.get("rashi", ""),
                    "rashi_hi": lagna_raw.get("rashi_hi", ""),
                    "navamsha": lagna_raw.get("navamsha_sign", ""),
                    "navamsha_hi": lagna_raw.get("navamsha_sign_hi", ""),
                    "nakshatra": lagna_raw.get("nakshatra", ""),
                    "lagnesh": lagna_raw.get("rashi_lord", ""),
                },
                "planets": {
                    p: {
                        "house": ph_raw.get(p),
                        "rashi": d.get("rashi"),
                        "rashi_hi": d.get("rashi_hi"),
                        "navamsha": d.get("navamsha_sign"),
                        "navamsha_hi": d.get("navamsha_sign_hi"),
                        "nakshatra": d.get("nakshatra"),
                        "dignity": d.get("dignity", ""),
                        "degree": d.get("degree_in_sign"),
                    }
                    for p, d in planets_raw.items()
                },
                "houses": {
                    str(h["house"]): {
                        "sign": h["sign"],
                        "lord": h["lord"],
                        "lord_in_house": h["lord_house"],
                        "planets": h["occupants"],
                    }
                    for h in computed_houses
                },
                "dasha": chart.get("dasha", {}),
                "dasha_by_decade": chart.get("dasha_by_decade", {}),
            }

        return {
            "title": "Trividha Kundli Vishleshan",
            "janam_kundli": _fallback_block("janam", "जन्म कुंडली" if is_hindi else "Janam Kundli", "जीवन-दीर्घ योजना" if is_hindi else "Lifelong Blueprint"),
            "prashna_kundli": _fallback_block("prashna", "प्रश्न कुंडली" if is_hindi else "Prashna Kundli", "अगले ३-९ माह" if is_hindi else "Next 3-9 Months", include_decades=True),
            "gochar_kundli": _fallback_block("gochar", "गोचर कुंडली" if is_hindi else "Gochar Kundli", "अगले १२-१८ माह" if is_hindi else "Next 12-18 Months"),
            "chart_summary": chart_summary,
            "multi_system_analysis": {
                "framework": "Structure -> Meaning -> Timing -> Confirmation (Parashar -> Jaimini -> KP -> Bhrigu)",
                "natal": multi_system_natal,
                "gochar": multi_system_gochar,
                "prashna": multi_system_prashna,
            },
            "next_feature": {
                "title": "Rapid Guidance",
                "summary": (
                    "Model response slow hone par chart-aadharit quick reading di gayi hai."
                    if is_hindi else
                    "A chart-based quick reading is provided because the model response was slow."
                ),
                "timeframe": "Agle 30 din" if is_hindi else "Next 30 days",
                "priority_actions": [
                    "Daily routine discipline",
                    "Financial tracking",
                    "Clear communication",
                    "Weekly planning review",
                    "Spiritual grounding",
                ],
                "caution_points": [
                    "Avoid impulsive commitments",
                    "Avoid over-analysis without action",
                    "Keep emotional balance in key decisions",
                ],
            },
            "system_note": reason,
        }

    # Serialize to JSON so the prompt carries exact factual data
    _h_facts = [
        {
            "house": h["house"],
            "name": h["name"],
            "sign": h["sign"],
            "lord": h["lord"],
            "lord_in_house": h["lord_house"],
            "planets_here": h["occupants"],
        }
        for h in computed_houses
    ]
    houses_json_str = json.dumps(_h_facts, ensure_ascii=False)

    prompt = f"""You are Fortune Guru -- a highly precise Vedic astrologer (30+ years experience).

USER: {user.first_name} | DOB: {user.dob} | Time: {user.tob} | Place: {user.place}
Lucky Number: {user.selected_number}
{chart_text}

DECADE DASHA MAPPING (computed from Moon nakshatra -- MUST use for decade_predictions):
{decade_ctx}

=== AUTHORITATIVE HOUSE DATA (Swiss Ephemeris -- DO NOT CHANGE) ===
{houses_json_str}
=== END HOUSE DATA ===

STRICT RULES:
1. The HOUSE DATA above is 100% factually correct. Do NOT move any planet to a different house.
   If "planets_here" is empty for a house, no planet occupies it. Do NOT invent occupants.
   If "planets_here" has ["Sun"], ONLY Sun is there -- do NOT mention any other planet for that house.
2. In the "houses" array: copy "house","name","sign","lord" exactly from HOUSE DATA. Leave "analysis" empty.
   FILL EXACTLY TWO FIELDS — NEVER mix their content:

   "prediction" = JEEVAN PHAL ONLY (life effects, 3-5 sentences).
     What the lord/occupant planets mean for this person's life in the house theme.
     GOOD: "Lagna mein Surya hone se aapka vyaktitva tej aur aatmavishwasi hai. Aap jeevan mein netritva bhumika pasand karte hain."
     NO mantra/ratan/daan in this field.

   "upay" = VEDIC REMEDIES ONLY (mantra, ratan, daan, rang, din, devata).
     GOOD: "Pratidin Surya ko jal chadhayein. Manik ratan dharein. Ravi ko gehun daan karein."
     WRONG (DO NOT DO): "Is ghar mein planet hone se aapko labh hoga..." ← yeh prediction hai, upay nahi.
     ONLY practical remedies — no jeevan phal sentences in upay.
3. In prediction/detailed_prediction text: use planet names and house numbers ONLY as they
   appear in HOUSE DATA above. No invented placements.
4. All dasha references MUST use: {maha} Mahadasha / {antar} Antardasha.
5. Never refer to yourself as AI/model/assistant. Use only "Guru Ji" as self-reference.
6. SECTION DIFFERENTIATION IS MANDATORY (no copy/paste across sections):
    - janam_kundli = natal life blueprint (core personality, karmic tendencies, lifelong patterns).
    - gochar_kundli = current transit-style effects and near-term shifts (next 12-18 months).
    - prashna_kundli = immediate outcome-focused reading (next 3-9 months), decisive and practical.
    The 3 sections must NOT repeat the same sentences.
7. For each house prediction, write 3 temporal layers with concrete life-event style statements:
    - Past pattern (Ateet): what pattern/events likely repeated earlier in life.
    - Present activation (Vartaman): what is active now and why.
    - Future trend (Bhavishya): what likely unfolds next, with timing cues from dasha.
    Keep prediction 6-9 sentences total, chart-grounded, and specific.
8. In each section and each house, explicitly include impacts on relatives/family, friends/network, and workplace atmosphere.
9. HEALTH MAPPING IS MANDATORY for each house:
   - Add body mapping from Kalpurush axis (1=head ... 12=feet/sleep) and likely issue tendencies.
   - Use house + house lord + occupants/aspects logic in explanation.
   - Dusthana caution: houses 6/8/12 must carry stronger medical vigilance note.
10. Writing style must be Vedic Rishi-vani: prophetic and dignified, as if planets themselves are revealing outcomes, while remaining factual and chart-based.
11. In every major section, start with one engaging "Divya Sanket" opener and end with one actionable "Agla Karm Sankalp" closer.

TASK: Return ONE valid JSON object. ALL text values in {lang_instr}.

JSON SCHEMA:
{{{{
  "title": "meaningful title for this specific reading",
  "janam_kundli": {{{{
        "prediction": "3-4 sentences: natal blueprint only (stable personality + karmic life themes)",
        "detailed_prediction": "300+ words: include Ateet/Vartaman/Bhavishya with periods; cover relatives, friends/network, workplace atmosphere; Vedic Rishi-vani tone",
    "next_steps": ["4-5 action strings tied to chart strengths"],
    "houses": [
      {{{{
        "house": <integer 1-12 from HOUSE DATA>,
        "name": "<copy from HOUSE DATA>",
        "sign": "<copy from HOUSE DATA>",
        "lord": "<copy from HOUSE DATA>",
        "analysis": "",
                                "body_parts": "kalpurush body mapping string for this house",
                                "possible_issues": ["3-4 likely issue tendencies for this house"],
                                "health_note": "house+lord+occupant based caution line (Dusthana emphasis for 6/8/12)",
                "prediction": "[JEEVAN PHAL] 8-12 sentences with 3 layers: (Ateet pattern + period) + (Vartaman activation + period) + (Bhavishya trend + timing cues). Must include relatives/family, friends/network, workplace atmosphere, and real-life event signals.",
        "upay": "[REMEDIES ONLY] Mantra: ... Ratan: ... Daan: ... Devata: ... (NO prediction text here, sirf upay)"
      }}}}
    ]
  }}}},
  "prashna_kundli": {{{{
        "prediction": "3-4 sentences: immediate/practical outcome focus (next 3-9 months)",
        "detailed_prediction": "260+ words: decisive current-phase reading with Ateet/Vartaman/Bhavishya, practical outcomes, relatives/friends/workplace atmosphere, and precise timing",
    "next_steps": ["4-5 strings"],
    "houses": [same schema -- analysis empty, prediction and upay only],
    "decade_predictions": [
      {{{{
        "age_range": "X-Y",
        "dasha_lords": "<from DECADE DASHA MAPPING>",
        "predictions": ["cite dasha lord + natal placement", "career/family trend", "key turning point"]
      }}}}
    ]
  }}}},
  "gochar_kundli": {{{{
        "prediction": "3-4 sentences: near-term movement, opportunities/challenges (next 12-18 months)",
        "detailed_prediction": "260+ words: transit-driven shifts with Ateet/Vartaman/Bhavishya periods, plus relatives/friends/workplace atmosphere effects; distinct from janam/prashna",
    "next_steps": ["4-5 strings"],
    "houses": [same schema]
  }}}},
  "next_feature": {{{{
    "title": "string", "summary": "string",
    "timeframe": "specific months e.g. March-June 2026",
    "priority_actions": ["5 strings each naming a planet/house"],
    "caution_points": ["3 strings naming debilitated/afflicted planets"]
  }}}}
}}}}

CRITICAL: Return ONLY valid JSON. No markdown. No code fences."""

    try:
        response = await generate_content_with_timeout(
            prompt,
            generation_config={"response_mime_type": "application/json"},
            timeout_seconds=KUNDLI_MODEL_TIMEOUT_SECONDS,
        )
        raw_text = getattr(response, "text", "").strip()
        parsed = _extract_json_block(raw_text)

        if not parsed:
            return _build_fallback_payload(
                "Structured kundli response parse nahi ho paaya; fast fallback diya gaya."
            )

        # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        def _decade_fallback(age_range: str, lords_str: str, language: str) -> List[str]:
            """Generate dasha-informed fallback predictions for a decade."""
            start_age = int(age_range.split("-")[0]) if "-" in age_range else 0
            # Extract first dasha lord name from lords_str like "Saturn(3.2yr), Jupiter(1.5yr)"
            first_lord = re.search(r"([A-Za-z]+)\(", lords_str)
            lord_name = first_lord.group(1) if first_lord else "the ruling planet"

            # Dasha lord keywords for narrative
            lord_traits = {
                "Saturn": ("discipline, hard work, delays that build strength", "karm, mehnat, sangh kathinaai jo mazbuuti deti hai"),
                "Jupiter": ("wisdom, expansion, blessings and growth", "gyan, vistaar, aashirwaad aur unnati"),
                "Mars": ("courage, ambition, energy and drive", "sahas, ichchha-shakti, urja aur prayas"),
                "Venus": ("comfort, creativity, relationships and pleasure", "sukh, srijan, prem aur anand"),
                "Mercury": ("intellect, communication, business acumen", "buddhi, sanvaad, vyapaarik dakshata"),
                "Moon": ("emotions, home, mother, fluctuation", "bhaavnayen, ghar, maa, utaar-chadhaav"),
                "Sun": ("authority, self-confidence, recognition", "pratishtha, aatm-vishwaas, pahachaan"),
                "Rahu": ("ambition, foreign, unconventional jumps", "mahattvakansha, videshi, anokhe badlaav"),
                "Ketu": ("spirituality, detachment, past karma", "adhyaatm, vairagya, purvjanm karm"),
            }
            trait_en, trait_hi = lord_traits.get(lord_name, ("growth and change", "vikaas aur parivartan"))

            if language == "hi":
                return [
                    f"Ye dashak {lord_name} dasha (ya antar) ke prabhav mein hai â€” {trait_hi} ke kshetra mein mulayam ya teevra anubhav milenge.",
                    f"Is aayu-khand mein {lord_name} ki dasha ke anusar kareer aur vyaktigatv mein ek nishchit disha banega.",
                    f"Is daur ki chunautiyon se judkar aage ke dashak ke liye ek pokhta nà¥€à¤‚v tayaar hogi.",
                ]
            return [
                f"This decade runs under {lord_name} dasha â€” themes of {trait_en} dominate life choices.",
                f"Career and personal growth in this phase align closely with {lord_name}'s placement in the natal chart.",
                f"Challenges faced now lay the foundation for the following decade's achievements.",
            ]

        def _normalize_decade_predictions(raw_timeline, language: str) -> List[dict]:
            try:
                dob_date = datetime.strptime(user.dob, "%Y-%m-%d").date()
                today = datetime.now().date()
                current_age = today.year - dob_date.year - (
                    (today.month, today.day) < (dob_date.month, dob_date.day))
            except Exception:
                current_age = 30
            max_age = min(max(70, ((current_age + 20) // 10) * 10), 90)

            ai_map: dict = {}
            if isinstance(raw_timeline, list):
                for item in raw_timeline:
                    if not isinstance(item, dict):
                        continue
                    ar = str(item.get("age_range", "")).strip()
                    m_obj = re.match(r"^(\d{1,2})\s*-\s*(\d{1,2})$", ar)
                    if not m_obj:
                        continue
                    s = int(m_obj.group(1))
                    e = int(m_obj.group(2))
                    if e - s != 10:
                        continue
                    preds = item.get("predictions", [])
                    if not isinstance(preds, list):
                        preds = []
                    preds = [str(p).strip() for p in preds if str(p).strip()][:3]
                    ai_map[s] = {
                        "age_range": f"{s}-{e}",
                        "dasha_lords": str(item.get("dasha_lords", dasha_by_decade.get(f"{s}-{e}", ""))),
                        "predictions": preds,
                    }

            result = []
            for start_age in range(0, max_age, 10):
                ar_key = f"{start_age}-{start_age + 10}"
                lords_str = dasha_by_decade.get(ar_key, "")
                if start_age in ai_map and len(ai_map[start_age]["predictions"]) >= 2:
                    entry = ai_map[start_age]
                    if not entry.get("dasha_lords"):
                        entry["dasha_lords"] = lords_str
                    result.append(entry)
                else:
                    result.append({
                        "age_range": ar_key,
                        "dasha_lords": lords_str,
                        "predictions": _decade_fallback(ar_key, lords_str, language),
                    })
            return result

        def normalize_kundli_block(block_name: str, block_value,
                                   include_decade_timeline: bool = False) -> dict:
            if not isinstance(block_value, dict):
                block_value = {}

            # ── Step 1: AI houses -- take "prediction" and "upay" from AI response ──
            ai_prediction_map: dict = {}
            ai_advice_map: dict = {}
            ai_body_map: dict = {}
            ai_issues_map: dict = {}
            ai_health_note_map: dict = {}
            for h in (block_value.get("houses", []) or []):
                if isinstance(h, dict):
                    try:
                        num = int(h.get("house", 0))
                    except (TypeError, ValueError):
                        num = 0
                    if num:
                        ai_prediction_map[num] = str(h.get("prediction", "")).strip()
                        # accept both "upay" and fallback "advice" for backward compat
                        ai_advice_map[num] = str(h.get("upay") or h.get("advice", "")).strip()
                        ai_body_map[num] = str(h.get("body_parts", "")).strip()
                        raw_issues = h.get("possible_issues", [])
                        if isinstance(raw_issues, list):
                            ai_issues_map[num] = [str(x).strip() for x in raw_issues if str(x).strip()][:5]
                        else:
                            ai_issues_map[num] = []
                        ai_health_note_map[num] = str(h.get("health_note", "")).strip()

            # ── Step 2: Build authoritative houses from Swiss Ephemeris ──
            def _fallback_house(idx: int) -> dict:
                med = _house_medical_profile(idx, user.language)
                return {
                    "house": idx, "name": f"House {idx}",
                    "sign": "", "lord": "",
                    "analysis": "Computed data unavailable.",
                    "prediction": ai_prediction_map.get(idx, ""),
                    "body_parts": ai_body_map.get(idx) or med["body_parts"],
                    "possible_issues": ai_issues_map.get(idx) or med["possible_issues"],
                    "health_note": ai_health_note_map.get(idx) or _health_risk_note(idx, "", [], user.language),
                    "advice": ai_advice_map.get(idx, ""),
                }

            if computed_houses:
                normalized_houses = []
                for ch in computed_houses:
                    h_num = ch["house"]
                    med = _house_medical_profile(h_num, user.language)
                    occ = ch.get("occupants", []) if isinstance(ch.get("occupants", []), list) else []
                    normalized_houses.append({
                        "house": h_num,
                        "name": ch.get("name", f"House {h_num}"),
                        "sign": ch.get("sign", ""),
                        "lord": ch.get("lord", ""),
                        "analysis": ch.get("analysis", ""),      # factual from Swiss Ephemeris
                        "prediction": ai_prediction_map.get(h_num, ""),  # AI life-effect prediction
                        "body_parts": ai_body_map.get(h_num) or med["body_parts"],
                        "possible_issues": ai_issues_map.get(h_num) or med["possible_issues"],
                        "health_note": ai_health_note_map.get(h_num) or _health_risk_note(h_num, ch.get("lord", ""), occ, user.language),
                        "advice": ai_advice_map.get(h_num, ""),           # AI practical guidance
                    })
                # Pad to 12 if _build_computed_houses returned fewer
                while len(normalized_houses) < 12:
                    normalized_houses.append(_fallback_house(len(normalized_houses) + 1))
            else:
                # Fallback: use old AI-based normalization when chart unavailable
                normalized_houses = []
                houses_raw = block_value.get("houses", []) or []
                for idx, h in enumerate(houses_raw[:12], start=1):
                    med = _house_medical_profile(idx, user.language)
                    normalized_houses.append({
                        "house": int(h.get("house", idx)) if isinstance(h, dict) else idx,
                        "name": str(h.get("name", f"House {idx}")) if isinstance(h, dict) else f"House {idx}",
                        "sign": str(h.get("sign", "")) if isinstance(h, dict) else "",
                        "lord": str(h.get("lord", "")) if isinstance(h, dict) else "",
                        "analysis": str(h.get("analysis", "Analysis unavailable.")) if isinstance(h, dict) else "Analysis unavailable.",
                        "prediction": str(h.get("prediction", "")) if isinstance(h, dict) else "",
                        "body_parts": str(h.get("body_parts", med["body_parts"])) if isinstance(h, dict) else med["body_parts"],
                        "possible_issues": [str(x).strip() for x in (h.get("possible_issues", med["possible_issues"]) if isinstance(h, dict) else med["possible_issues"]) if str(x).strip()][:5],
                        "health_note": str(h.get("health_note", _health_risk_note(idx, str(h.get("lord", "")) if isinstance(h, dict) else "", [], user.language))) if isinstance(h, dict) else _health_risk_note(idx, "", [], user.language),
                        "advice": str(h.get("advice", "")) if isinstance(h, dict) else "",
                    })
                while len(normalized_houses) < 12:
                    normalized_houses.append(_fallback_house(len(normalized_houses) + 1))

            # ── Step 3: Next steps ──
            steps_raw = block_value.get("next_steps", [])
            if not isinstance(steps_raw, list):
                steps_raw = []
            steps = [str(s).strip() for s in steps_raw if str(s).strip()][:5]
            while len(steps) < 3:
                steps.extend([
                    "Routine discipline maintain karein.",
                    "Daily reflection aur planning karein.",
                    "Impulsive decisions se bachkar practical steps lein.",
                ][:3 - len(steps)])

            det_pred = str(block_value.get("detailed_prediction", "")).strip()
            short_pred = str(block_value.get("prediction", "")).strip()
            if not short_pred and det_pred:
                short_pred = det_pred

            normalized: dict = {
                "prediction": short_pred or f"{block_name} prediction unavailable.",
                "detailed_prediction": det_pred,
                "analysis_structure": str(block_value.get("analysis_structure", "")).strip(),
                "analysis_meaning": str(block_value.get("analysis_meaning", "")).strip(),
                "analysis_timing": str(block_value.get("analysis_timing", "")).strip(),
                "analysis_confirmation": str(block_value.get("analysis_confirmation", "")).strip(),
                "kp_core": block_value.get("kp_core", {}) if isinstance(block_value.get("kp_core", {}), dict) else {},
                "next_steps": steps,
                "houses": normalized_houses,
            }

            if include_decade_timeline:
                normalized["decade_predictions"] = _normalize_decade_predictions(
                    block_value.get("decade_predictions", []),
                    user.language,
                )

            return normalized


        # â”€â”€ Build final response â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        janam = normalize_kundli_block("Janam Kundli", parsed.get("janam_kundli", {}))
        prashna = normalize_kundli_block("Prashna Kundli", parsed.get("prashna_kundli", {}),
                                         include_decade_timeline=True)
        gochar = normalize_kundli_block("Gochar Kundli", parsed.get("gochar_kundli", {}))

        janam["analysis_structure"] = multi_system_natal.get("framework", janam.get("analysis_structure", ""))
        janam["analysis_meaning"] = multi_system_natal.get("life_overview", janam.get("analysis_meaning", ""))
        janam["analysis_timing"] = multi_system_natal.get("event_timing", janam.get("analysis_timing", ""))
        janam["analysis_confirmation"] = multi_system_natal.get("confirmation_notes", janam.get("analysis_confirmation", ""))
        janam["kp_core"] = multi_system_natal.get("kp_core", janam.get("kp_core", {}))

        gochar["analysis_structure"] = multi_system_gochar.get("framework", gochar.get("analysis_structure", ""))
        gochar["analysis_meaning"] = multi_system_gochar.get("life_overview", gochar.get("analysis_meaning", ""))
        gochar["analysis_timing"] = multi_system_gochar.get("event_timing", gochar.get("analysis_timing", ""))
        gochar["analysis_confirmation"] = multi_system_gochar.get("confirmation_notes", gochar.get("analysis_confirmation", ""))
        gochar["kp_core"] = multi_system_gochar.get("kp_core", gochar.get("kp_core", {}))

        prashna["analysis_structure"] = multi_system_prashna.get("framework", prashna.get("analysis_structure", ""))
        prashna["analysis_meaning"] = multi_system_prashna.get("life_overview", prashna.get("analysis_meaning", ""))
        prashna["analysis_timing"] = multi_system_prashna.get("event_timing", prashna.get("analysis_timing", ""))
        prashna["analysis_confirmation"] = multi_system_prashna.get("confirmation_notes", prashna.get("analysis_confirmation", ""))
        prashna["kp_core"] = multi_system_prashna.get("kp_core", prashna.get("kp_core", {}))

        # If chart was computed, inject computed lagna/dasha into Janam prediction header
        if chart and chart.get("lagna") and not janam["detailed_prediction"].strip():
            lg = chart["lagna"]
            janam["prediction"] = (
                f"Lagna: {lg['rashi_hi']} ({lg['rashi']}), "
                f"Lagnesh: {lg['rashi_lord']}. "
                + janam["prediction"]
            )

        next_feature = parsed.get("next_feature", {})
        if not isinstance(next_feature, dict):
            next_feature = {}

        priority_actions = next_feature.get("priority_actions", [])
        if not isinstance(priority_actions, list):
            priority_actions = []
        priority_actions = [str(i).strip() for i in priority_actions if str(i).strip()][:5]

        caution_points = next_feature.get("caution_points", [])
        if not isinstance(caution_points, list):
            caution_points = []
        caution_points = [str(i).strip() for i in caution_points if str(i).strip()][:3]

        if not priority_actions:
            priority_actions = [
                "Subah ka structured routine follow karein.",
                "Career aur finances ke top 3 goals likhkar execute karein.",
                "Relationship communication clear rakhein.",
                "Weekly health check routine banayein.",
                "Daily gratitude aur dhyan practice karein.",
            ]

        # Build chart_summary — raw Swiss Ephemeris data for QA context
        chart_summary: dict = {}
        if chart:
            lagna_raw = chart.get("lagna", {})
            planets_raw = chart.get("planets", {})
            ph_raw = chart.get("planet_houses", {})
            chart_summary = {
                "lagna": {
                    "rashi": lagna_raw.get("rashi", ""),
                    "rashi_hi": lagna_raw.get("rashi_hi", ""),
                    "navamsha": lagna_raw.get("navamsha_sign", ""),
                    "navamsha_hi": lagna_raw.get("navamsha_sign_hi", ""),
                    "nakshatra": lagna_raw.get("nakshatra", ""),
                    "lagnesh": lagna_raw.get("rashi_lord", ""),
                },
                "planets": {
                    p: {
                        "house": ph_raw.get(p),
                        "rashi": d.get("rashi"),
                        "rashi_hi": d.get("rashi_hi"),
                        "navamsha": d.get("navamsha_sign"),
                        "navamsha_hi": d.get("navamsha_sign_hi"),
                        "nakshatra": d.get("nakshatra"),
                        "dignity": d.get("dignity", ""),
                        "degree": d.get("degree_in_sign"),
                    }
                    for p, d in planets_raw.items()
                },
                "houses": {
                    str(h["house"]): {
                        "sign": h["sign"],
                        "lord": h["lord"],
                        "lord_in_house": h["lord_house"],
                        "planets": h["occupants"],
                    }
                    for h in computed_houses
                },
                "dasha": chart.get("dasha", {}),
                "dasha_by_decade": chart.get("dasha_by_decade", {}),
            }

        result_payload = {
            "title": str(parsed.get("title", "Trividha Kundli Vishleshan")),
            "janam_kundli": janam,
            "prashna_kundli": prashna,
            "gochar_kundli": gochar,
            "chart_summary": chart_summary,
            "multi_system_analysis": {
                "framework": "Structure -> Meaning -> Timing -> Confirmation (Parashar -> Jaimini -> KP -> Bhrigu)",
                "natal": multi_system_natal,
                "gochar": multi_system_gochar,
                "prashna": multi_system_prashna,
            },
            "next_feature": {
                "title": str(next_feature.get("title", "Next Feature Activated: Personal Action Blueprint")),
                "summary": str(next_feature.get("summary", "Aapke chart inputs ke basis par actionable plan generate kiya gaya hai.")),
                "timeframe": str(next_feature.get("timeframe", "Agle 90 din")),
                "priority_actions": priority_actions,
                "caution_points": caution_points,
            },
        }

        if hi and _kundli_payload_has_hinglish(result_payload):
            return _build_fallback_payload(
                "भाषा शुद्धता नियम सक्रिय: हिंग्लिश सामग्री मिली, इसलिए शुद्ध देवनागरी वैकल्पिक पाठ प्रस्तुत किया गया।"
            )

        return _normalize_self_reference(result_payload)
    except asyncio.TimeoutError:
        return _build_fallback_payload(
            f"Prediction service timeout ({int(KUNDLI_MODEL_TIMEOUT_SECONDS)}s); fast fallback response returned."
        )
    except Exception as e:
        print("KUNDLI API ERROR:", repr(e))
        return _build_fallback_payload(f"API fallback activated: {repr(e)}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8010"))
    uvicorn.run(app, host="127.0.0.1", port=port)

