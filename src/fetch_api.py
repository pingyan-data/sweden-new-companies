"""Enrich this week's new companies via the Värdefulla datamängder API.

The API is a lookup-by-orgnr service, so it can't *find* new companies — the
bulk file does that. Here we look up the new ones (filtered by org form,
capped at MAX_API_LOOKUPS) to get extra fields, e.g. SCB industry codes.

Writes:
  data/raw/api/YYYY-MM-DD_api_raw.jsonl         full response per orgnr
  data/raw/api/YYYY-MM-DD_api_normalized.jsonl  flattened (dotted keys)
"""
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

from config import (API_BASE, API_ORG_FORMS, API_SCOPE, API_SLEEP_S, CLIENT_ID,
                    CLIENT_SECRET, MAX_API_LOOKUPS, RAW_API, RAW_BULK,
                    TOKEN_URL, USER_AGENT, read_jsonl, run_date, update_status,
                    write_jsonl)


def get_token() -> str:
    r = requests.post(TOKEN_URL, timeout=30,
                      data={"grant_type": "client_credentials", "scope": API_SCOPE},
                      auth=(CLIENT_ID, CLIENT_SECRET),
                      headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()["access_token"]


def flatten(obj, prefix="", out=None, max_list=20) -> dict:
    """{'a': {'b': [1, {'c': 2}]}} -> {'a.b.0': 1, 'a.b.1.c': 2}. Schema-agnostic."""
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}{k}.", out, max_list)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:max_list]):
            flatten(v, f"{prefix}{i}.", out, max_list)
    else:
        out[prefix[:-1]] = obj
    return out


def lookup(session: requests.Session, orgnr: str, token_box: list) -> requests.Response:
    for attempt in range(4):
        r = session.post(f"{API_BASE}/organisationer",
                         json={"identitetsbeteckning": orgnr}, timeout=30,
                         headers={"Authorization": f"Bearer {token_box[0]}",
                                  "X-Request-Id": str(uuid.uuid4()),
                                  "User-Agent": USER_AGENT})
        if r.status_code == 401 and attempt == 0:      # token expired → refresh once
            token_box[0] = get_token()
            continue
        if r.status_code in (429, 500, 502, 503, 504):  # back off and retry
            time.sleep(5 * (attempt + 1))
            continue
        return r
    return r


def main() -> int:
    today = run_date()
    src = RAW_BULK / f"{today}_bolagsverket_normalized.jsonl"
    if not src.exists():
        update_status("api", {"state": "skipped (no events today)"})
        return 0
    if not (CLIENT_ID and CLIENT_SECRET):
        print("No API credentials set — skipping enrichment.")
        update_status("api", {"state": "skipped (no credentials)"})
        return 0

    orgnrs = sorted({r["orgnr"] for r in read_jsonl(src)
                     if r["event_type"] == "new_registration"
                     and (not API_ORG_FORMS or r["org_form"] in API_ORG_FORMS)})
    todo = orgnrs[:MAX_API_LOOKUPS]
    print(f"{len(orgnrs)} candidates, looking up {len(todo)} (forms={API_ORG_FORMS})")

    try:
        token_box = [get_token()]
    except Exception as e:  # noqa: BLE001
        update_status("api", {"state": "failed", "error": f"token: {str(e)[:200]}"})
        return 1

    raw_out, norm_out, errors = [], [], 0
    with requests.Session() as s:
        for orgnr in todo:
            r = lookup(s, orgnr, token_box)
            try:
                body = r.json()
            except ValueError:
                body = {"_text": r.text[:2000]}
            ok = r.status_code == 200
            errors += not ok
            fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
            raw_out.append({"orgnr": orgnr, "http_status": r.status_code,
                            "fetched_at": fetched, "response": body})
            if ok:
                norm_out.append({"orgnr": orgnr, **flatten(body)})
            time.sleep(API_SLEEP_S)

    write_jsonl(RAW_API / f"{today}_api_raw.jsonl", raw_out)
    write_jsonl(RAW_API / f"{today}_api_normalized.jsonl", norm_out)
    stats = {"candidates": len(orgnrs), "looked_up": len(todo),
             "ok": len(norm_out), "errors": errors}
    print(stats)
    # Every single lookup failing = something is wrong (auth, schema, endpoint).
    failed = bool(todo) and not norm_out
    update_status("api", {"state": "failed" if failed else "ok", **stats})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
