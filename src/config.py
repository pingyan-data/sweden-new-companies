"""Shared paths, settings and small helpers.

Every setting can be overridden with an environment variable, so the same
code runs locally (export VAR=...) and in GitHub Actions (vars / secrets).
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_BULK = DATA / "raw" / "bulk"
RAW_API = DATA / "raw" / "api"
PROCESSED = DATA / "processed"
TMP = DATA / "tmp"        # gitignored: the ~250 MB zip lives here, never in git
DEBUG = DATA / "debug"    # gitignored: probe output
STATUS_JSON = DATA / "status.json"
STATUS_MD = ROOT / "status.md"
BULK_ZIP = TMP / "bolagsverket_bulkfil.zip"

# --- Bulk file (no key needed) ----------------------------------------------
# Copy the link behind "bolagsverket_bulkfil.zip" on Bolagsverket's page
# "Nedladdningsbara filer" and store it as a repo *variable* (not a secret).
BULK_URL = os.environ.get("BOLAGSVERKET_BULK_URL", "").strip()
MIN_EXPECTED_ROWS = int(os.environ.get("MIN_EXPECTED_ROWS", "1000000"))

# --- API (OAuth2 client credentials) ----------------------------------------
CLIENT_ID = os.environ.get("BOLAGSVERKET_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("BOLAGSVERKET_CLIENT_SECRET", "").strip()
TOKEN_URL = os.environ.get(
    "BOLAGSVERKET_TOKEN_URL", "https://portal.api.bolagsverket.se/oauth2/token")
API_BASE = os.environ.get(
    "BOLAGSVERKET_API_BASE", "https://gw.api.bolagsverket.se/vardefulla-datamangder/v1")
API_SCOPE = "vardefulla-datamangder:read vardefulla-datamangder:ping"

# Which organisation forms to enrich via the API (codes as they appear in the
# bulk file after stripping the "-ORGFO" suffix; run probe_bulk.py to see them).
API_ORG_FORMS = [s.strip() for s in os.environ.get("API_ORG_FORMS", "AB").split(",") if s.strip()]
MAX_API_LOOKUPS = int(os.environ.get("MAX_API_LOOKUPS", "300"))
API_SLEEP_S = float(os.environ.get("API_SLEEP_S", "0.5"))

# --- Event detection ----------------------------------------------------------
# Look back this many days for registrations / deregistrations, then drop the
# ones already recorded in earlier weeks. A window wider than 7 days catches
# late-registered records and survives a skipped week.
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "35"))

USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "sweden-new-companies/0.1 (weekly open-data tracker)")


def run_date() -> str:
    """Snapshot date (UTC). Override with RUN_DATE=YYYY-MM-DD for testing."""
    return os.environ.get("RUN_DATE") or datetime.now(timezone.utc).date().isoformat()


def window_start(d: str) -> str:
    return (date.fromisoformat(d) - timedelta(days=WINDOW_DAYS)).isoformat()


def load_status() -> dict:
    if STATUS_JSON.exists():
        return json.loads(STATUS_JSON.read_text(encoding="utf-8"))
    return {}


def update_status(section: str, data: dict) -> None:
    status = load_status()
    status[section] = {"run_date": run_date(), **data}
    status["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
