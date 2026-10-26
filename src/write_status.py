"""Render data/status.json as status.md — a health check you can read on GitHub."""
from config import STATUS_MD, load_status, run_date

ICON = {"ok": "✅", "downloaded": "✅", "unchanged": "⏸️", "failed": "❌"}


def main() -> None:
    s = load_status()
    today = run_date()
    lines = [
        "# Pipeline status", "",
        f"Last run: **{today}** (UTC). Updated by GitHub Actions — do not edit by hand.", "",
        "| Step | Ran | State | Details |", "|---|---|---|---|",
    ]
    for step in ("bulk", "events", "api", "processed"):
        d = dict(s.get(step, {}))
        ran = d.pop("run_date", "—")
        state = d.pop("state", "never run")
        icon = ICON.get(state.split(" ")[0], "➖")
        if ran != today and ran != "—":
            icon, state = "⚠️", f"{state} (stale — did not run today)"
        details = ", ".join(f"{k}: {v}" for k, v in d.items() if not isinstance(v, dict))
        lines.append(f"| {step} | {ran} | {icon} {state} | {details} |")

    forms = s.get("events", {}).get("new_by_org_form")
    if forms:
        lines += ["", "New registrations by organisation form (this run):", ""]
        lines += [f"- {k or '(blank)'}: {v}" for k, v in forms.items()]
    STATUS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
