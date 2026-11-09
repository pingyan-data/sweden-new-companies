"""Download this week's bolagsverket_bulkfil.zip into data/tmp/ (gitignored).

* Resumable: if the connection drops mid-download, continue with an HTTP Range
  request from the bytes already received (up to BULK_MAX_ATTEMPTS tries).
* Skips the download if Last-Modified equals last week's (FORCE=1 overrides).
* Fails if the source hasn't been updated for more than 10 days.
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

MAX_ATTEMPTS = int(os.environ.get("BULK_MAX_ATTEMPTS", "8"))


class NotAZip(RuntimeError):
    """Wrong URL (HTML page / captcha). Retrying won't help."""


def _sha256(path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, prev_last_modified: str | None):
    BULK_ZIP.parent.mkdir(parents=True, exist_ok=True)
    part = BULK_ZIP.with_name(BULK_ZIP.name + ".part")
    part.unlink(missing_ok=True)
    total = etag = None
    lm = ctype = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
            if etag:
                headers["If-Range"] = etag   # resume only if the file hasn't changed
        try:
            with requests.get(url, stream=True, timeout=(30, 120), headers=headers) as r:
                if r.status_code == 416 and total and have >= total:
                    break                     # already complete
                r.raise_for_status()
                if r.status_code == 206:
                    mode = "ab"
                    print(f"Resuming at {have / 1e6:.0f} MB")
                else:                         # fresh start (or server ignored Range)
                    mode = "wb"
                    lm = r.headers.get("Last-Modified", "")
                    ctype = r.headers.get("Content-Type", "")
                    etag = r.headers.get("ETag")
                    total = int(r.headers.get("Content-Length") or 0) or None
                    if lm and lm == prev_last_modified and os.environ.get("FORCE") != "1":
                        return {"state": "unchanged", "last_modified": lm}
                    if "text/html" in ctype:
                        raise NotAZip(
                            f"Got HTML instead of a zip (Content-Type {ctype}). "
                            "The URL is probably a web page or a captcha, not the file link.")
                with part.open(mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            size = part.stat().st_size
            if total and size < total:
                raise IOError(f"incomplete: {size}/{total} bytes")
            break
        except NotAZip:
            raise
        except (requests.RequestException, IOError) as e:
            got = part.stat().st_size if part.exists() else 0
            print(f"Attempt {attempt}/{MAX_ATTEMPTS} interrupted at {got / 1e6:.0f} MB: {str(e)[:150]}")
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(min(15 * attempt, 120))

    if not zipfile.is_zipfile(part):
        raise RuntimeError("Downloaded file is not a valid zip")
    part.replace(BULK_ZIP)
    return {"state": "downloaded", "last_modified": lm, "content_type": ctype,
            "size_mb": round(BULK_ZIP.stat().st_size / 1e6, 1), "sha256": _sha256(BULK_ZIP)}


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
