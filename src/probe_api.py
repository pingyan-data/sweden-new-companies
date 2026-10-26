"""One-off: check credentials and see the real API response structure.

    export BOLAGSVERKET_CLIENT_ID=...
    export BOLAGSVERKET_CLIENT_SECRET=...
    python src/probe_api.py              # default: Volvo 5560125790
    python src/probe_api.py 5591234567   # any 10-digit orgnr

Never prints the token or secret. Full responses go to data/debug/ (gitignored).
"""
import json
import sys
import uuid

import requests

from config import API_BASE, CLIENT_ID, CLIENT_SECRET, DEBUG, USER_AGENT
from fetch_api import flatten, get_token


def show(name: str, r: requests.Response) -> None:
    print(f"\n== {name}: HTTP {r.status_code}, {len(r.content)} bytes, "
          f"Content-Type {r.headers.get('Content-Type')}")
    try:
        body = r.json()
    except ValueError:
        print(r.text[:1000])
        return
    DEBUG.mkdir(parents=True, exist_ok=True)
    (DEBUG / f"probe_api_{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False))
    print("Fields (flattened):")
    for k, v in list(flatten(body).items())[:80]:
        print(f"  {k} = {str(v)[:80]}")


def main() -> None:
    if not (CLIENT_ID and CLIENT_SECRET):
        sys.exit("Set BOLAGSVERKET_CLIENT_ID and BOLAGSVERKET_CLIENT_SECRET first.")
    orgnr = sys.argv[1] if len(sys.argv) > 1 else "5560125790"

    try:
        token = get_token()
        print("Token: OK")
    except requests.HTTPError as e:
        sys.exit(f"Token request failed: HTTP {e.response.status_code} {e.response.text[:500]}\n"
                 "Check: ID/secret swapped? Production vs test (accept2) credentials?")

    h = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    show("isalive", requests.get(f"{API_BASE}/isalive",
                                 headers={**h, "X-Request-Id": str(uuid.uuid4())}, timeout=30))
    for ep in ("organisationer", "dokumentlista"):
        show(ep, requests.post(f"{API_BASE}/{ep}", json={"identitetsbeteckning": orgnr},
                               headers={**h, "X-Request-Id": str(uuid.uuid4())}, timeout=30))
    print(f"\nFull JSON saved in {DEBUG}/. If you got HTTP 400, read the error body:"
          " it usually names the expected request field.")


if __name__ == "__main__":
    main()
