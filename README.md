# Sweden New Company Tracker

A weekly tracker of companies registered and deregistered in Sweden, built on Bolagsverket's free **Värdefulla datamängder** (EU high-value datasets).

**Why this exists.** Bolagsverket publishes the whole company register as a free weekly bulk file, but only the *latest* version stays online. Without collecting it every week, there is no time series of registrations. This repo builds that series automatically.

**Status.** Pipeline scaffolded (2026-10-26). Live data pending first run. See [`status.md`](status.md) for the latest run.

---

## How it works

```
Tuesday 06:00 UTC (GitHub Actions)
   │
   ├─ fetch_bulk.py        download bolagsverket_bulkfil.zip (~250 MB, NOT committed)
   ├─ extract_events.py    stream ~3 M rows → this week's new registrations & deregistrations
   ├─ fetch_api.py         look up new companies in the API (extra fields, e.g. industry codes)
   ├─ build_processed.py   join → one analysis file per week
   ├─ archive_bulk.py      (optional) full snapshot as Parquet → GitHub Release
   ├─ write_status.py      status.md health check
   └─ commit + push        `git pull` on your laptop to get the data
```

**Why bulk file + API, not API alone.** The API looks companies up by organisation number. It cannot answer "what was registered this week". The bulk file can, through the `registreringsdatum` / `avregistreringsdatum` fields. The API then adds detail for the new companies only.

**Event detection without storing last week's 1 GB file.** Each run keeps rows whose registration or deregistration date falls in the last `WINDOW_DAYS` (35) days. It then drops events already recorded in earlier weeks (`event_key = type:orgnr:name_seq`). The wide window catches late-registered records and survives a missed week. On the **first run** you get a 35-day backfill.

## Data layout

```
data/
├── raw/bulk/   YYYY-MM-DD_bolagsverket_raw.jsonl         untouched rows for this week's events
│               YYYY-MM-DD_bolagsverket_normalized.jsonl  flat view, English field names
│               YYYY-MM-DD_bolagsverket_bulk_meta.json    Last-Modified, size, sha256
├── raw/api/    YYYY-MM-DD_api_raw.jsonl                  full API response per orgnr
│               YYYY-MM-DD_api_normalized.jsonl           flattened (dotted keys)
├── processed/  YYYY-MM-DD_events.jsonl                   analysis-ready, one line per event
└── status.json                                           machine-readable run status
```

JSONL = one JSON object per line: `wc -l` gives the count, and `for line in f` streams it. Only the week's events are committed, a few MB per week, so the repo stays well under 1 GB for years.

## Setup (one time)

1. **Bulk file link.** Open Bolagsverket's page *API:er och öppna data → Hämta företagsinformation → Nedladdningsbara filer*. Right-click `bolagsverket_bulkfil.zip` and choose *Copy link address*. In the repo, go to **Settings → Secrets and variables → Actions → Variables → New repository variable**: name `BOLAGSVERKET_BULK_URL`, value = the link.
2. **API credentials.** These are in the email *"Anslutningsuppgifter för Värdefulla datamängder"*. Same page, **Secrets** tab, create two repository secrets: `BOLAGSVERKET_CLIENT_ID` and `BOLAGSVERKET_CLIENT_SECRET`.
3. **Alerts.** In your personal GitHub settings, go to **Settings → Notifications → System → Actions** and choose *Only notify for failed workflows*.
4. **First run.** Open the **Actions** tab, select **weekly-fetch**, and click **Run workflow**. Then check that a commit landed and that `status.md` is all ✅.

Optional repository variables:

| Variable | Default | Meaning |
|---|---|---|
| `API_ORG_FORMS` | `AB` | Org forms to enrich via the API (comma-separated, codes as in the bulk file) |
| `MAX_API_LOOKUPS` | `300` | Cap on API calls per run |
| `ARCHIVE_TO_RELEASE` | *(off)* | `true` = archive the full weekly file as a Release asset |

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in, never commit
set -a; source .env; set +a

python src/probe_bulk.py        # look at the real file first
python src/probe_api.py         # check credentials + response structure

python src/fetch_bulk.py && python src/extract_events.py \
  && python src/fetch_api.py && python src/build_processed.py && python src/write_status.py
```

## Bulk file gotchas (verify with `probe_bulk.py`)

- `;`-separated, quoted, UTF-8, 11 columns, ~3 M rows, ~1 GB unpacked. It is published Monday night, hence the Tuesday cron.
- It is **not a plain CSV**. Structured values are packed into one field with `$` between parts and `|` between list items, e.g. `5560125790$ORGNR-IDORG`. See `bulk_reader.normalize()`.
- Descriptions contain line breaks, so rows ≠ records. Always use a CSV parser.
- The same orgnr can appear on several rows (`namnskyddslopnummer`). This is why `name_seq` is part of the event key.
- The file contains the full history, and most rows are deregistered companies.
- Code lists (org forms, deregistration reasons) are not inside the file. See Bolagsverket's kodlista on the download page.

## Monitoring

- Each step can fail without stopping the others. **Any** failure turns the run red and sends an email.
- If the source file has not changed for more than 10 days, the run fails. One late publish is tolerated, a dead source is not.
- If there are fewer than 1 M rows, the run fails, because it is probably a broken or truncated file.
- `status.md` shows the last run per step at a glance.

## Development log

### 2026-10-26 — Session 1: design

- Got API credentials for Värdefulla datamängder (OAuth2 client credentials).
- Found that the API is lookup-only, so the bulk file is the PRIMARY source and the API is enrichment.
- Scaffolded the pipeline using the patterns from [sweden-data-job-market](https://github.com/pingyan-data/sweden-data-job-market): one script per source, `_raw` + `_normalized`, probe before fetch, pinned runner, and monitoring from day one.

### Next sessions (planned)

- Run both probes; confirm the org form codes and the API response fields.
- Promote useful API fields (e.g. SNI industry code) to top-level columns in `build_processed.py`.
- Weekly counts by org form, municipality and industry, and a first chart.

## Source & license

Data: Bolagsverket and SCB, Värdefulla datamängder (EU Implementing Regulation 2023/138). The data is free to reuse. This project is not affiliated with Bolagsverket.
