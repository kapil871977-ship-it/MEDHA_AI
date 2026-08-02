"""
API-level tests for MEDHA AI: authentication, endpoint protection, rate
limiting, saved-reading history, and the language/self-reference helpers.

These run entirely offline (no LLM keys, no network) via FastAPI's TestClient.

Run from the backend/ directory:
    pytest
"""
import importlib

import pytest

# Test configuration (temp DB, fixed secret, LLM keys cleared) is applied in
# conftest.py so it lands before any test module imports `main`.
main = importlib.import_module("main")
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)

PROTECTED_ENDPOINTS = ["/kundli-analysis", "/full-analysis", "/section-qa", "/tezi-mandi"]


@pytest.fixture(autouse=True)
def _clear_rate_buckets():
    """Rate-limit state is process-global; reset it between tests."""
    main._RATE_BUCKET.clear()
    yield
    main._RATE_BUCKET.clear()


def _signup(identifier, password="secret123"):
    return client.post("/auth/signup", json={"identifier": identifier, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ─── Health ──────────────────────────────────────────────────────────────────

def test_health_reports_provider_status():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    for key in ("openai_configured", "gemini_configured", "llm_available"):
        assert key in body


# ─── Signup / login ──────────────────────────────────────────────────────────

def test_signup_returns_token():
    body = _signup("alice@example.com").json()
    assert body.get("token")
    assert body["identifier"] == "alice@example.com"


def test_signup_rejects_duplicate():
    _signup("dupe@example.com")
    assert "error" in _signup("dupe@example.com").json()


def test_signup_rejects_short_password():
    body = _signup("shorty@example.com", password="12345").json()
    assert "error" in body
    assert "token" not in body


def test_signup_normalizes_identifier_case():
    _signup("MixedCase@Example.com")
    body = client.post(
        "/auth/login",
        json={"identifier": "mixedcase@example.com", "password": "secret123"},
    ).json()
    assert body.get("token")


def test_login_succeeds_with_correct_password():
    _signup("bob@example.com")
    body = client.post(
        "/auth/login", json={"identifier": "bob@example.com", "password": "secret123"}
    ).json()
    assert body.get("token")


def test_login_rejects_wrong_password():
    _signup("carol@example.com")
    body = client.post(
        "/auth/login", json={"identifier": "carol@example.com", "password": "wrongpass"}
    ).json()
    assert "error" in body
    assert "token" not in body


def test_login_rejects_unknown_user():
    body = client.post(
        "/auth/login", json={"identifier": "nobody@example.com", "password": "secret123"}
    ).json()
    assert "error" in body


def test_passwords_are_never_stored_in_plaintext():
    _signup("hash@example.com", password="plaintextpw")
    conn = main._auth_db()
    try:
        row = conn.execute(
            "SELECT pw_hash, pw_salt FROM users WHERE identifier = ?", ("hash@example.com",)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "plaintextpw" not in row[0]
    assert main._verify_password("plaintextpw", row[0], row[1])
    assert not main._verify_password("plaintextpwX", row[0], row[1])


# ─── Tokens ──────────────────────────────────────────────────────────────────

def test_auth_me_accepts_bearer_header():
    token = _signup("me@example.com").json()["token"]
    body = client.get("/auth/me", headers=_auth_header(token)).json()
    assert body == {"authenticated": True, "identifier": "me@example.com"}


def test_auth_me_rejects_tampered_token():
    token = _signup("tamper@example.com").json()["token"]
    payload_b64, sig = token.split(".", 1)
    forged = f"{payload_b64}.{'0' * len(sig)}"
    body = client.get("/auth/me", headers=_auth_header(forged)).json()
    assert body["authenticated"] is False


def test_expired_token_is_rejected():
    original_ttl = main.AUTH_TOKEN_TTL_SECONDS
    try:
        main.AUTH_TOKEN_TTL_SECONDS = -10   # already expired on issue
        expired = main._make_token("expired@example.com")
    finally:
        main.AUTH_TOKEN_TTL_SECONDS = original_ttl
    assert main._verify_token(expired) is None


# ─── Endpoint protection ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PROTECTED_ENDPOINTS)
def test_protected_endpoints_reject_missing_token(path):
    assert client.post(path, json={}).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_ENDPOINTS)
def test_protected_endpoints_reject_garbage_token(path):
    res = client.post(path, json={}, headers=_auth_header("not.a.real.token"))
    assert res.status_code == 401


def test_valid_token_passes_the_auth_gate():
    token = _signup("gate@example.com").json()["token"]
    # 422 = got past auth and failed body validation, which is what we want here.
    res = client.post("/section-qa", json={}, headers=_auth_header(token))
    assert res.status_code == 422


def test_history_endpoints_require_auth():
    assert client.get("/history").status_code == 401
    assert client.get("/history/1").status_code == 401
    assert client.delete("/history/1").status_code == 401


# ─── Rate limiting ───────────────────────────────────────────────────────────

def test_auth_endpoints_are_rate_limited():
    original = main.AUTH_RATE_LIMIT_PER_MINUTE
    main.AUTH_RATE_LIMIT_PER_MINUTE = 3
    try:
        codes = [
            client.post(
                "/auth/login",
                json={"identifier": "brute@example.com", "password": f"guess{i}"},
            ).status_code
            for i in range(5)
        ]
    finally:
        main.AUTH_RATE_LIMIT_PER_MINUTE = original
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_heavy_endpoints_are_rate_limited():
    token = _signup("ratelimit@example.com").json()["token"]
    original = main.RATE_LIMIT_PER_MINUTE
    main.RATE_LIMIT_PER_MINUTE = 2
    try:
        codes = [
            client.post("/section-qa", json={}, headers=_auth_header(token)).status_code
            for _ in range(4)
        ]
    finally:
        main.RATE_LIMIT_PER_MINUTE = original
    assert codes == [422, 422, 429, 429]


def test_auth_and_api_rate_limits_use_separate_buckets():
    token = _signup("buckets@example.com").json()["token"]
    main.AUTH_RATE_LIMIT_PER_MINUTE = 1
    main.RATE_LIMIT_PER_MINUTE = 5
    try:
        client.post("/auth/login", json={"identifier": "buckets@example.com", "password": "x"})
        # The auth bucket is now full; the API bucket must be unaffected.
        res = client.post("/section-qa", json={}, headers=_auth_header(token))
        assert res.status_code == 422
    finally:
        main.AUTH_RATE_LIMIT_PER_MINUTE = 0
        main.RATE_LIMIT_PER_MINUTE = 0


# ─── Saved-reading history ───────────────────────────────────────────────────

def _sample_user(name="Test User"):
    return main.UserInput(
        first_name=name, dob="1995-07-17", tob="14:30", place="New Delhi",
        selected_number=5, language="hi", lat=28.6139, lng=77.2090,
    )


def test_history_roundtrip_list_get_delete():
    token = _signup("hist@example.com").json()["token"]
    headers = _auth_header(token)

    assert client.get("/history", headers=headers).json()["items"] == []

    main._save_kundli_report("hist@example.com", _sample_user(), {"title": "Reading One"})
    items = client.get("/history", headers=headers).json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Reading One"
    assert items[0]["dob"] == "1995-07-17"

    report_id = items[0]["id"]
    got = client.get(f"/history/{report_id}", headers=headers).json()
    assert got["report"]["title"] == "Reading One"

    assert client.delete(f"/history/{report_id}", headers=headers).json()["deleted"] is True
    assert client.get("/history", headers=headers).json()["items"] == []
    assert client.get(f"/history/{report_id}", headers=headers).status_code == 404


def test_history_is_scoped_per_account():
    owner_token = _signup("owner@example.com").json()["token"]
    other_token = _signup("other@example.com").json()["token"]

    main._save_kundli_report("owner@example.com", _sample_user(), {"title": "Private"})
    report_id = client.get("/history", headers=_auth_header(owner_token)).json()["items"][0]["id"]

    assert client.get("/history", headers=_auth_header(other_token)).json()["items"] == []
    assert client.get(f"/history/{report_id}", headers=_auth_header(other_token)).status_code == 404
    assert client.delete(f"/history/{report_id}", headers=_auth_header(other_token)).status_code == 404
    # Still intact for its owner.
    assert client.get(f"/history/{report_id}", headers=_auth_header(owner_token)).status_code == 200


def test_history_is_pruned_to_the_configured_limit():
    token = _signup("prune@example.com").json()["token"]
    original = main.KUNDLI_HISTORY_LIMIT
    main.KUNDLI_HISTORY_LIMIT = 3
    try:
        for i in range(6):
            main._save_kundli_report("prune@example.com", _sample_user(), {"title": f"R{i}"})
        items = client.get("/history", headers=_auth_header(token)).json()["items"]
    finally:
        main.KUNDLI_HISTORY_LIMIT = original

    assert len(items) == 3
    assert [i["title"] for i in items] == ["R5", "R4", "R3"]   # newest first


# ─── Language / self-reference helpers ───────────────────────────────────────

def test_self_reference_normalizer_preserves_ordinary_words():
    for text in ("He is a role model.", "The business model is sound.",
                 "AIIMS Delhi", "Mainly focused on results."):
        assert main._normalize_self_reference(text) == text


def test_self_reference_normalizer_rewrites_self_disclosure():
    for text in ("As an AI language model, I cannot predict.",
                 "I am an AI assistant.", "Guruji ne kaha", "Pandit ji ne bataya"):
        assert "Guru Ji" in main._normalize_self_reference(text)
    assert "AI" not in main._normalize_self_reference("As an AI language model, I cannot.")


def test_self_reference_normalizer_skips_computed_chart_data():
    payload = {"chart_summary": {"planets": {"Sun": {"nakshatra": "Magha"}}},
               "janam_kundli": {"prediction": "Guruji kehte hain"}}
    out = main._normalize_self_reference(payload)
    assert out["chart_summary"]["planets"]["Sun"]["nakshatra"] == "Magha"
    assert out["janam_kundli"]["prediction"] == "Guru Ji kehte hain"


def test_devanagari_reading_with_latin_proper_nouns_is_accepted():
    payload = {"janam_kundli": {
        "prediction": (
            "आपका लग्न मेष है और लग्नेश Mars दशम भाव में स्थित है। "
            "Guru Ji के अनुसार यह समय अनुशासन और परिश्रम का है।"
        ),
        "detailed_prediction": "वर्तमान में Saturn Mahadasha चल रही है, धैर्य रखें।",
        "next_steps": ["नियमित ध्यान करें।"],
        "houses": [],
    }}
    assert main._kundli_payload_has_hinglish(payload) is False


def test_romanized_hindi_reading_is_rejected():
    payload = {"janam_kundli": {
        "prediction": "Aapka lagna Mesh hai aur lagnesh dasham bhav mein sthit hai.",
        "detailed_prediction": "Abhi Saturn Mahadasha chal rahi hai, dhairya rakhein.",
        "next_steps": ["Roz dhyan karein."],
        "houses": [],
    }}
    assert main._kundli_payload_has_hinglish(payload) is True


def test_answer_style_matching_tolerates_expected_latin():
    hindi = ("हाँ, विवाह के प्रबल योग हैं। Guru Ji के अनुसार Venus Antardasha "
             "समाप्त होने पर शुभ समय आएगा और कार्य सिद्ध होगा।")
    assert main._answer_matches_style(hindi, "hi") is True
    assert main._answer_matches_style(
        "Haan vivah ke prabal yog hain, Venus Antardasha ke baad shubh samay aayega.", "hi"
    ) is False
    assert main._answer_matches_style(
        "Yes, marriage is likely under Venus Antardasha ending March 2027.", "en"
    ) is True


# ─── Tezi-Mandi instrument resolution & pricing ──────────────────────────────

def test_bank_nifty_does_not_resolve_to_nifty_50():
    """"nifty" is a substring of "bank nifty" — longest alias must win."""
    assert main._product_market_symbols("Bank Nifty") == ["^NSEBANK"]
    assert main._product_market_symbols("banknifty") == ["^NSEBANK"]
    assert main._product_market_symbols("Nifty 50") == ["^NSEI"]
    assert main._product_karaka_planets("Bank Nifty") != main._product_karaka_planets("Nifty 50")


def test_every_suggested_product_resolves_to_a_symbol():
    """Products offered in the UI dropdown must map to a real quote symbol."""
    offered = [
        "Gold", "Silver", "Crude Oil", "Natural Gas", "Copper", "Aluminium",
        "Nifty 50", "Bank Nifty", "Sensex", "USDINR", "EURINR", "JPYINR",
        "Soybean", "Corn", "Cotton", "Sugar", "Wheat", "Rice", "Coffee",
        "Bitcoin", "Ethereum",
    ]
    unmapped = [p for p in offered if not main._product_market_symbols(p)]
    assert unmapped == [], f"no market symbol for: {unmapped}"


def test_quote_profiles_use_the_real_exchange_currency_and_unit():
    gold = main._price_unit_profile("Gold")
    assert gold["currency"] == "USD"          # COMEX, not INR
    assert gold["base_unit"] == "troy ounce"  # not "10g"

    nifty = main._price_unit_profile("Nifty 50")
    assert nifty["currency"] == "INR"
    assert nifty["unit_kg"] is None           # an index has no mass

    wheat = main._price_unit_profile("Wheat")
    assert wheat["cents"] is True             # CBOT quotes US cents per bushel


def test_gold_price_breakdown_is_dimensionally_correct():
    # 1 troy ounce = 31.1034768 g, so USD 3110.34768/oz is exactly USD 100/g.
    b = main._price_breakdown(3110.34768, "Gold")
    assert b["currency"] == "USD"
    assert b["base_unit"] == "troy ounce"
    assert round(b["per_gram"], 6) == 100.0
    assert round(b["per_kg"], 3) == 100_000.0


def test_cents_quoted_grains_are_converted_to_whole_currency():
    # 675 US cents per bushel = USD 6.75 per bushel; a bushel of wheat = 27.2155 kg.
    b = main._price_breakdown(675.0, "Wheat")
    assert round(b["price"], 4) == 6.75
    assert round(b["per_kg"], 4) == round(6.75 / 27.2155, 4)


def test_index_quotes_have_no_mass_derived_rows():
    b = main._price_breakdown(24000.0, "Nifty 50")
    assert b["currency"] == "INR"
    assert b["per_gram"] is None and b["per_kg"] is None and b["per_quintal"] is None


def test_inr_conversion_applied_only_to_foreign_currency_quotes():
    usd = main._price_breakdown(100.0, "Gold", usd_inr_rate=90.0)
    assert usd["inr_per_base_unit"] == 9000.0
    assert usd["fx_usd_inr"] == 90.0

    # An already-INR instrument is passed through, not multiplied by FX.
    inr = main._price_breakdown(24000.0, "Nifty 50", usd_inr_rate=90.0)
    assert inr["inr_per_base_unit"] == 24000.0

    # No FX rate available -> no INR figure invented.
    assert main._price_breakdown(100.0, "Gold")["inr_per_base_unit"] is None


def test_unknown_product_is_not_mislabelled():
    b = main._price_breakdown(123.45, "SomeUnknownThing")
    assert b["currency"] == ""        # never claims a currency it doesn't know
    assert b["per_kg"] is None


def test_question_style_detection():
    assert main._detect_question_style("मेरी शादी कब होगी?") == "hi"
    assert main._detect_question_style("Mera vivah kab hoga aur kya yeh shubh hai?") == "hinglish"
    assert main._detect_question_style("When will I get married?") == "en"


@pytest.mark.parametrize("question", [
    "Mera career kaisa rahega?",
    "Naukri milegi ya nahi?",
    "Paisa kitna aayega?",
    "Meri shaadi kab hogi?",
    "Ghar kab banega?",
    "Videsh jane ka yog hai kya?",
    "Mujhe kaunsa upay karna chahiye?",
])
def test_short_hinglish_questions_are_not_mistaken_for_english(question):
    """Real questions are short; the marker list must still catch them.

    These all previously scored below the 2-marker threshold and were answered
    in English, which is the wrong language for the person who asked.
    """
    assert main._detect_question_style(question) == "hinglish"


@pytest.mark.parametrize("question", [
    "How will my career progress?",
    "When will I get married?",
    "Will I travel abroad this year?",
    "What remedies should I do?",
    "Is this a good time to invest in gold?",
    "Tell me about my health this year.",
    "Main Street office relocation timing?",   # 'main' is also a Hindi marker
])
def test_plain_english_questions_stay_english(question):
    """Broadening the Hinglish markers must not swallow ordinary English."""
    assert main._detect_question_style(question) == "en"


def test_devanagari_always_wins_regardless_of_markers():
    assert main._detect_question_style("मेरा career kaisa रहेगा?") == "hi"
