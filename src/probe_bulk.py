"""One-off: look at the real bulk file before trusting the fetcher.

    python src/probe_bulk.py            # downloads to data/tmp/ if not there yet
    python src/probe_bulk.py --no-download

Prints headers, zip contents, sample rows, code lists and date coverage.
Takes ~1–3 min (streams ~3 M rows). Output also saved to data/debug/.
"""
import json
import sys
from collections import Counter
from datetime import date, timedelta

import requests

from bulk_reader import iter_rows, normalize
from config import BULK_URL, BULK_ZIP, DEBUG, USER_AGENT


def main() -> None:
    if not BULK_ZIP.exists() and "--no-download" not in sys.argv:
        if not BULK_URL:
            sys.exit("Set BOLAGSVERKET_BULK_URL first (see README → Setup).")
        print(f"Downloading {BULK_URL} …")
        with requests.get(BULK_URL, stream=True, timeout=(30, 300),
                          headers={"User-Agent": USER_AGENT}) as r:
            print("Status:", r.status_code)
            for h in ("Content-Type", "Content-Length", "Last-Modified", "ETag"):
                print(f"  {h}: {r.headers.get(h)}")
            r.raise_for_status()
            BULK_ZIP.parent.mkdir(parents=True, exist_ok=True)
            with BULK_ZIP.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    print(f"Zip size: {BULK_ZIP.stat().st_size / 1e6:.0f} MB")

    rows = bad = 0
    samples, bad_samples = [], []
    forms, reasons, id_types, proceedings = Counter(), Counter(), Counter(), Counter()
    orgnrs = set()
    reg_by_week = Counter()
    recent = (date.today() - timedelta(days=56)).isoformat()

    for rec, raw in iter_rows(BULK_ZIP):
        rows += 1
        if rec is None:
            bad += 1
            if len(bad_samples) < 3:
                bad_samples.append(raw)
            continue
        n = normalize(rec)
        if len(samples) < 5:
            samples.append({"raw": rec, "normalized": n})
        orgnrs.add(n["orgnr"])
        forms[n["org_form"]] += 1
        reasons[n["deregistration_reason"]] += 1
        id_types[n["id_type"]] += 1
        for p in n["proceedings"]:
            proceedings[p] += 1
        if n["registration_date"] >= recent:
            try:
                d = date.fromisoformat(n["registration_date"])
                reg_by_week[(d - timedelta(days=d.weekday())).isoformat()] += 1
            except ValueError:
                reg_by_week["unparseable"] += 1

    report = {
        "rows": rows, "malformed": bad, "unique_orgnr": len(orgnrs),
        "org_forms": forms.most_common(), "deregistration_reasons": reasons.most_common(),
        "id_types": id_types.most_common(), "proceedings": proceedings.most_common(),
        "registrations_per_week_last_8w": sorted(reg_by_week.items()),
        "samples": samples, "malformed_samples": bad_samples,
    }
    DEBUG.mkdir(parents=True, exist_ok=True)
    (DEBUG / "probe_bulk.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for k, v in report.items():
        if k not in ("samples", "malformed_samples"):
            print(f"{k}: {v}")
    print("\nFirst sample:\n", json.dumps(samples[0], indent=2, ensure_ascii=False))
    print(f"\nFull report: {DEBUG / 'probe_bulk.json'}")


if __name__ == "__main__":
    main()
