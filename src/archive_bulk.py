"""(Optional) Convert the full weekly bulk file to Parquet for a GitHub Release.

Why: Bolagsverket only keeps the *latest* file online. If you ever want to
diff full snapshots (e.g. detect name/address changes, new bankruptcies),
you need your own archive. Release assets don't count toward repo size.

Output: data/tmp/YYYY-MM-DD_bolagsverket_bulkfil.parquet (all columns as strings,
zstd-compressed). The workflow uploads it with `gh release create`.
"""
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from bulk_reader import EXPECTED_COLUMNS, iter_rows
from config import BULK_ZIP, TMP, run_date

BATCH = 200_000


def main() -> int:
    if not BULK_ZIP.exists():
        print("No bulk zip this run (unchanged or failed) — nothing to archive.")
        return 0
    out = TMP / f"{run_date()}_bolagsverket_bulkfil.parquet"
    schema = pa.schema([(c, pa.string()) for c in EXPECTED_COLUMNS])
    buf = {c: [] for c in EXPECTED_COLUMNS}
    rows = bad = 0
    with pq.ParquetWriter(out, schema, compression="zstd") as w:
        for rec, _ in iter_rows(BULK_ZIP):
            if rec is None:
                bad += 1
                continue
            for c in EXPECTED_COLUMNS:
                buf[c].append(rec.get(c, ""))
            rows += 1
            if rows % BATCH == 0:
                w.write_table(pa.table(buf, schema=schema))
                buf = {c: [] for c in EXPECTED_COLUMNS}
        if buf[EXPECTED_COLUMNS[0]]:
            w.write_table(pa.table(buf, schema=schema))
    print(f"Wrote {out} ({rows} rows, {bad} malformed skipped, "
          f"{out.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
