"""Find this week's new registrations and deregistrations in the bulk file.

Logic (no need to keep last week's 1 GB file around):
  1. Stream all ~3 M rows once.
  2. Keep rows whose registreringsdatum or avregistreringsdatum falls inside
     the last WINDOW_DAYS days.
  3. Drop events already written in earlier weeks (event_key seen before).

Sole traders (id_type PERSON) are identified by personnummer = personal data.
They are NEVER written to this (public) repo:
  * PRIVATE_DIR set   -> written there (a checkout of the private data repo)
  * PRIVATE_DIR unset -> skipped

Writes:
  data/raw/bulk/YYYY-MM-DD_bolagsverket_raw.jsonl          companies (public)
  data/raw/bulk/YYYY-MM-DD_bolagsverket_normalized.jsonl
  $PRIVATE_DIR/YYYY-MM-DD_bolagsverket_persons_raw.jsonl    sole traders (private)
  $PRIVATE_DIR/YYYY-MM-DD_bolagsverket_persons_normalized.jsonl
"""
import os
import sys
from collections import Counter
from pathlib import Path

from bulk_reader import iter_rows, normalize
from config import (BULK_ZIP, MIN_EXPECTED_ROWS, RAW_BULK, load_status,
                    read_jsonl, run_date, update_status, window_start,
                    write_jsonl)

PRIVATE_DIR = Path(os.environ["PRIVATE_DIR"]) if os.environ.get("PRIVATE_DIR") else None

EVENT_TYPES = {"new_registration": "registration_date",
               "deregistration": "deregistration_date"}


def event_key(event_type: str, n: dict) -> str:
    return f"{event_type}:{n['orgnr']}:{n['name_seq']}"


def seen_keys(today: str) -> set[str]:
    """Event keys from earlier weeks, public and private (today's files excluded so re-runs are safe)."""
    keys = set()
    dirs = [RAW_BULK] + ([PRIVATE_DIR] if PRIVATE_DIR else [])
    for d in dirs:
        for p in sorted(d.glob("*_normalized.jsonl")):
            if p.name.startswith(today):
                continue
            keys.update(r["event_key"] for r in read_jsonl(p))
    return keys


def main() -> int:
    today = run_date()
    if load_status().get("bulk", {}).get("state") == "unchanged":
        print("Bulk file unchanged since last run, nothing to extract.")
        update_status("events", {"state": "skipped (bulk unchanged)"})
        return 0
    if not BULK_ZIP.exists():
        print(f"{BULK_ZIP} missing — did fetch_bulk.py fail?")
        update_status("events", {"state": "failed", "error": "bulk zip missing"})
        return 1

    since = window_start(today)
    seen = seen_keys(today)
    out = {"public": ([], []), "private": ([], [])}   # (raw, normalized)
    rows = bad = 0
    orgnrs = set()
    forms = Counter()
    max_reg = ""

    for rec, _ in iter_rows(BULK_ZIP):
        rows += 1
        if rec is None:
            bad += 1
            continue
        n = normalize(rec)
        orgnrs.add(n["orgnr"])
        max_reg = max(max_reg, n["registration_date"])
        is_person = n["id_type"] == "PERSON"
        if is_person and PRIVATE_DIR is None:
            continue
        target = out["private" if is_person else "public"]
        for etype, field in EVENT_TYPES.items():
            d = n[field]
            if d and since <= d <= today:
                key = event_key(etype, n)
                if key in seen:
                    continue
                seen.add(key)
                meta = {"event_type": etype, "event_date": d, "event_key": key,
                        "snapshot_date": today}
                target[0].append({**meta, "raw": rec})
                target[1].append({**meta, **n})
                if etype == "new_registration":
                    forms[n["org_form"]] += 1

    pub = Counter(r["event_type"] for r in out["public"][1])
    priv = Counter(r["event_type"] for r in out["private"][1])
    # Counts only — never print records, Actions logs of a public repo are public.
    stats = {
        "total_rows": rows, "malformed_rows": bad, "unique_orgnr": len(orgnrs),
        "latest_registration_date_in_file": max_reg, "window_start": since,
        "new_registrations": pub["new_registration"],
        "deregistrations": pub["deregistration"],
        "persons_new_registrations": priv["new_registration"] if PRIVATE_DIR else "not collected",
        "persons_deregistrations": priv["deregistration"] if PRIVATE_DIR else "not collected",
        "new_by_org_form": dict(forms.most_common(10)),
    }
    print(stats)

    if rows < MIN_EXPECTED_ROWS:
        update_status("events", {"state": "failed",
                                 "error": f"only {rows} rows (expected ≥ {MIN_EXPECTED_ROWS})", **stats})
        return 1

    write_jsonl(RAW_BULK / f"{today}_bolagsverket_raw.jsonl", out["public"][0])
    write_jsonl(RAW_BULK / f"{today}_bolagsverket_normalized.jsonl", out["public"][1])
    if PRIVATE_DIR:
        write_jsonl(PRIVATE_DIR / f"{today}_bolagsverket_persons_raw.jsonl", out["private"][0])
        write_jsonl(PRIVATE_DIR / f"{today}_bolagsverket_persons_normalized.jsonl", out["private"][1])
    update_status("events", {"state": "ok", **stats})
    return 0


if __name__ == "__main__":
    sys.exit(main())
