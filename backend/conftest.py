"""
Shared pytest setup.

`main` reads its configuration from the environment at import time, so these
must be set before any test module imports it. conftest.py is loaded first by
pytest, which guarantees that ordering regardless of which test file runs
first — without this, importing `main` from test_chart.py would bind the real
backend/users.db and the API tests would write to it.
"""
import os
import tempfile

os.environ.setdefault("AUTH_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="medha-test-"), "users.db"))
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("AUTH_ENFORCE", "true")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MINUTE", "0")

# Tests must never call a real LLM provider.
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ["GOOGLE_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
