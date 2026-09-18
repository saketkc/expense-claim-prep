#!/usr/bin/env python3
"""Black out every credit-card-statement transaction row except the ones the
caller says to keep. Redaction is real (page.apply_redactions removes the
underlying text objects on that page) -- not a black box painted over live
text. It does NOT scrub embedded images, PDF metadata, or other pages; if a
statement's table is a scanned image rather than live text, this script
can't help at all (there's no text to find/remove) -- rasterize the whole
page instead.

Assumes a table with one date per row in a fixed column, and that each kept
row contains at least one of the given --keep tokens as an EXACT word match
somewhere in that row (a reference number is ideal; an exact amount string,
as it literally appears in the table, also works).

Usage:
    python redact_statement.py IN.pdf OUT.pdf --keep 14067855696 14067601959

Scans every page by default and redacts each one that has a detectable
transaction table; pass --page to restrict to one page (0-indexed).

Fails closed: if a --keep token matches zero rows (typo, wrong token) or
more than one row (ambiguous -- pick a more specific token, e.g. the
reference number instead of an amount that repeats), it raises rather than
silently producing a wrong redaction.
"""
import argparse
import re
import sys
from collections import Counter

import pymupdf

DATE = re.compile(r"\d{2}[/-]\d{2}[/-]\d{2,4}")


def redact_page(page, keep: set[str], match_counts: Counter) -> int | None:
    """Redact one page's transaction table. Returns rows kept, or None if
    this page has no detectable date column (e.g. a cover/summary page)."""
    words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word_no)
    dates = [w for w in words if DATE.fullmatch(w[4])]
    if len(dates) < 2:
        return None
    # Most transaction tables repeat the same left x-position for every row's
    # date; a handful of one-off dates elsewhere on the page (statement
    # period, due date) won't form a majority column.
    col_x, col_count = Counter(round(w[0]) for w in dates).most_common(1)[0]
    if col_count < 2:
        return None
    rows = sorted([w for w in dates if abs(w[0] - col_x) < 2], key=lambda w: w[1])

    gaps = [b[1] - a[1] for a, b in zip(rows, rows[1:])]
    table_x1 = max(w[2] for w in words if w[0] >= col_x - 5) + 2

    kept = 0
    for i, r in enumerate(rows):
        top = r[1] - 2
        bot = rows[i + 1][1] - 2 if i + 1 < len(rows) else r[1] + max(gaps) - 2
        band = [w for w in words if top <= w[1] < bot and w[0] >= col_x - 5]
        row_matches = {tok for w in band for tok in keep if tok == w[4]}
        match_counts.update(row_matches)
        if row_matches:
            kept += 1
            continue
        x0 = min(w[0] for w in band) - 2
        y1 = max(w[3] for w in band) + 1
        page.add_redact_annot(pymupdf.Rect(x0, top, table_x1, y1), fill=(0, 0, 0))

    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    return kept


def redact(src: str, out: str, keep: set[str], page_no: int | None = None) -> tuple[int, int]:
    doc = pymupdf.open(src)
    pages = [doc[page_no]] if page_no is not None else list(doc)
    match_counts = Counter()

    total_kept = 0
    any_table_found = False
    for page in pages:
        result = redact_page(page, keep, match_counts)
        if result is None:
            continue
        any_table_found = True
        total_kept += result

    if not any_table_found:
        raise SystemExit("No transaction table found on the scanned page(s). "
                          "Pass --page to target the right page, or the table may be a scanned image (can't redact text that isn't there).")

    unmatched = keep - match_counts.keys()
    ambiguous = {tok: n for tok, n in match_counts.items() if n > 1}
    if unmatched:
        raise SystemExit(f"--keep token(s) matched no row, nothing was saved: {sorted(unmatched)}. "
                          "Check the token appears verbatim (exact word) in the table.")
    if ambiguous:
        raise SystemExit(f"--keep token(s) matched more than one row, nothing was saved: {ambiguous}. "
                          "Use a more specific token (e.g. the reference number instead of an amount that repeats).")

    doc.save(out, garbage=4, deflate=True)
    return sum(match_counts.values()), total_kept


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--keep", nargs="+", required=True, help="exact tokens (reference numbers or amounts, as they literally appear in the table) whose row stays visible")
    ap.add_argument("--page", type=int, default=None, help="0-indexed page to restrict to (default: scan all pages)")
    args = ap.parse_args()

    _, kept_rows = redact(args.src, args.out, set(args.keep), args.page)
    print(f"{args.out}: kept {kept_rows} row(s) visible across all matched pages", file=sys.stderr)
