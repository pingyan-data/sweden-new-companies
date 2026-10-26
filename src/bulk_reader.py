"""Read and normalize Bolagsverket's bulk file (bolagsverket_bulkfil.zip).

Format facts (verify with probe_bulk.py, they can change):
  * zip containing one .txt file, ';'-separated, every field quoted, UTF-8
  * 11 columns, ~3 M rows, ~1 GB unpacked
  * NOT a plain CSV: structured values are packed into one field with '$'
    between parts and '|' between list items, e.g.
        organisationsidentitet = "5560125790$ORGNR-IDORG"
        organisationsnamn      = "Name$FORETAGSNAMN-ORGNAM$1993-03-15|Other$SARS_FORNAMN-ORGNAM$..."
        postadress             = "street$c/o$CITY$POSTNR$SE-LAND"
  * descriptions contain line breaks -> must use a real CSV parser
  * a few rows contain backslash-escaped quotes (invalid CSV) -> escapechar
  * the same orgnr can appear on several rows (namnskyddslopnummer 1, 2, ...)
"""
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))  # some fields are huge

EXPECTED_COLUMNS = [
    "organisationsidentitet", "namnskyddslopnummer", "registreringsland",
    "organisationsnamn", "organisationsform", "avregistreringsdatum",
    "avregistreringsorsak", "pagandeAvvecklingsEllerOmstruktureringsforfarande",
    "registreringsdatum", "verksamhetsbeskrivning", "postadress",
]

_PROCEEDING_CODE = re.compile(r"([A-ZÅÄÖ0-9_]+)-AVOMFO")


def iter_rows(zip_path: Path):
    """Yield (record_dict_or_None, raw_row_list). None = malformed row."""
    with zipfile.ZipFile(zip_path) as zf:
        txt = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txt:
            raise RuntimeError(f"No .txt file inside {zip_path}: {zf.namelist()}")
        with zf.open(txt[0]) as fb:
            text = io.TextIOWrapper(fb, encoding="utf-8", errors="replace", newline="")
            reader = csv.reader(text, delimiter=";", quotechar='"',
                                escapechar="\\", doublequote=True)
            header = [h.strip().lstrip("\ufeff") for h in next(reader)]
            if header != EXPECTED_COLUMNS:
                print(f"WARNING: header changed!\n  expected {EXPECTED_COLUMNS}\n  got      {header}")
            for row in reader:
                if len(row) != len(header):
                    yield None, row
                else:
                    yield dict(zip(header, row)), row


def code(value: str) -> str:
    """'AB-ORGFO' -> 'AB', 'VERKUPP-AVORG' -> 'VERKUPP', '' -> ''."""
    return value.rsplit("-", 1)[0] if value else ""


def _part(parts, i):
    return parts[i] if len(parts) > i else ""


def parse_names(value: str) -> list[dict]:
    names = []
    for item in filter(None, value.split("|")):
        p = item.split("$")
        names.append({"name": _part(p, 0), "type": code(_part(p, 1)),
                      "date": _part(p, 2), "scope": _part(p, 3)})
    return names


def normalize(rec: dict) -> dict:
    """Flat view with English field names. Keeps nothing that raw doesn't have."""
    idp = rec["organisationsidentitet"].split("$")
    names = parse_names(rec["organisationsnamn"])
    primary = next((n for n in names if n["type"] == "FORETAGSNAMN"), names[0] if names else {})
    addr = rec["postadress"].split("$")
    proceedings = rec["pagandeAvvecklingsEllerOmstruktureringsforfarande"]
    return {
        "orgnr": _part(idp, 0),
        "id_type": code(_part(idp, 1)),
        "name_seq": rec["namnskyddslopnummer"],
        "name": primary.get("name", ""),
        "secondary_names": [n["name"] for n in names if n is not primary],
        "org_form": code(rec["organisationsform"]),
        "registration_date": rec["registreringsdatum"],
        "deregistration_date": rec["avregistreringsdatum"],
        "deregistration_reason": code(rec["avregistreringsorsak"]),
        "proceedings": _PROCEEDING_CODE.findall(proceedings),
        "proceedings_raw": proceedings,
        "description": rec["verksamhetsbeskrivning"],
        "street": _part(addr, 0),
        "care_of": _part(addr, 1),
        "city": _part(addr, 2),
        "postal_code": _part(addr, 3),
        "country": code(_part(addr, 4)),
    }
