"""Join the week's bulk events with API enrichment into one analysis file.

  data/processed/YYYY-MM-DD_events.jsonl

One line per event. New registrations that were looked up get top-level api_*
columns (field paths confirmed with probe_api.py on 2026-10-26).
"""
import sys

from config import (PROCESSED, RAW_API, RAW_BULK, read_jsonl, run_date,
                    update_status, write_jsonl)


def _get(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def api_fields(response: dict) -> dict:
    orgs = (response or {}).get("organisationer") or []
    if not orgs:
        return {"api_found": False}
    o = orgs[0]
    sni = [s for s in (_get(o, "naringsgrenOrganisation", "sni") or [])
           if (s.get("kod") or "").strip()]
    errors = {k: v["fel"] for k, v in o.items() if isinstance(v, dict) and v.get("fel")}
    return {
        "api_found": True,
        "sni_codes": [s["kod"].strip() for s in sni],
        "sni_labels": [s.get("klartext", "") for s in sni],
        "sni_primary": sni[0]["kod"].strip() if sni else None,
        "scb_legal_form_code": _get(o, "juridiskForm", "kod"),
        "scb_legal_form": _get(o, "juridiskForm", "klartext"),
        "scb_active": _get(o, "verksamOrganisation", "kod"),   # JA / NEJ / None
        "scb_registered_date": _get(o, "organisationsdatum", "infortHosScb"),
        "api_errors": errors or None,                          # e.g. not yet in SCB
    }


def main() -> int:
    today = run_date()
    src = RAW_BULK / f"{today}_bolagsverket_normalized.jsonl"
    if not src.exists():
        update_status("processed", {"state": "skipped (no events today)"})
        return 0

    api_path = RAW_API / f"{today}_api_raw.jsonl"
    api = {}
    if api_path.exists():
        for r in read_jsonl(api_path):
            if r["http_status"] == 200:
                api[r["orgnr"]] = api_fields(r["response"])

    out, with_sni = [], 0
    for e in read_jsonl(src):
        rec = {k: v for k, v in e.items() if k != "proceedings_raw"}
        if e["event_type"] == "new_registration" and e["orgnr"] in api:
            rec.update(api[e["orgnr"]])
            with_sni += bool(rec.get("sni_primary"))
        out.append(rec)

    n = write_jsonl(PROCESSED / f"{today}_events.jsonl", out)
    stats = {"state": "ok", "events": n, "enriched": len(api), "enriched_with_sni": with_sni}
    update_status("processed", stats)
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())