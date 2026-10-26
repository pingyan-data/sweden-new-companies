"""Download this week's bolagsverket_bulkfil.zip into data/tmp/ (gitignored).

Skips the download if the server's Last-Modified header is the same as last
week's (= Bolagsverket hasn't published a new file yet). FORCE=1 overrides.
Exit code 1 = failure (the workflow turns that into a red run + email).
"""
import hashlib
import json
import os
import sys
import time
import zipfile
from datetime import date

import requests

from config import (BULK_URL, BULK_ZIP, RAW_BULK, USER_AGENT, load_status,
                    run_date, update_status)


def download(url: str, prev_last_modified: str | None):
    for attempt in range(1, 4):
        try:
            with requests.get(url, stream=True, timeout=(30, 300),
                              headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                lm = r.headers.get("Last-Modified", "")
                ctype = r.headers.get("Content-Type", "")
                if lm and lm == prev_last_modified and os.environ.get("FORCE") != "1":
                    return {"state": "unchanged", "last_modified": lm}
                if "text/html" in ctype:
                    raise RuntimeError(
                        f"Got HTML instead of a zip (Content-Type {ctype}). "
                        "The URL is probably a web page or a captcha, not the file link.")
                BULK_ZIP.parent.mkdir(parents=True, exist_ok=True)
                h, size = hashlib.sha256(), 0
                with BULK_ZIP.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
            if not zipfile.is_zipfile(BULK_ZIP):
                raise RuntimeError("Downloaded file is not a valid zip")
            return {"state": "downloaded", "last_modified": lm, "content_type": ctype,
                    "size_mb": round(size / 1e6, 1), "sha256": h.hexdigest()}
        except Exception as e:  # noqa: BLE001
            print(f"Attempt {attempt} failed: {e}")
            if attempt == 3:
                raise
            time.sleep(30 * attempt)


def main() -> int:
    if not BULK_URL:
        print("BOLAGSVERKET_BULK_URL is not set. See README → Setup.")
        update_status("bulk", {"state": "failed", "error": "BOLAGSVERKET_BULK_URL not set"})
        return 1
    prev_status = load_status().get("bulk", {})
    prev = prev_status.get("last_modified")
    last_dl = prev_status.get("last_downloaded", "")
    try:
        info = download(BULK_URL, prev)
    except Exception as e:  # noqa: BLE001
        update_status("bulk", {"state": "failed", "error": str(e)[:300],
                               "last_modified": prev, "last_downloaded": last_dl})
        return 1

    if info["state"] == "unchanged":
        info["last_downloaded"] = last_dl
        # One unchanged week can be a late publish; two in a row means trouble.
        if last_dl and (date.fromisoformat(run_date()) - date.fromisoformat(last_dl)).days > 10:
            info["state"] = "failed"
            info["error"] = f"source file not updated since {last_dl}"
            update_status("bulk", info)
            return 1
    else:
        info["last_downloaded"] = run_date()

    print(json.dumps(info, indent=2))
    update_status("bulk", info)
    if info["state"] == "downloaded":
        RAW_BULK.mkdir(parents=True, exist_ok=True)
        meta = RAW_BULK / f"{run_date()}_bolagsverket_bulk_meta.json"
        meta.write_text(json.dumps({"url": BULK_URL, **info}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
