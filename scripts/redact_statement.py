#!/usr/bin/env python3
"""Black out every credit-card-statement transaction row except the ones the
caller says to keep, plus the account summary (dues, balances, limits,
spend breakdowns). Redaction is real (page.apply_redactions removes the
underlying text objects on that page) -- not a black box painted over live
text. It does NOT scrub embedded images, PDF metadata, or other pages; if a
statement's table is a scanned image rather than live text, this script
can't help at all (there's no text to find/remove) -- rasterize the whole
page instead.

Assumes a table with one date per row in a fixed column (dd/mm/yyyy,
dd-mm-yy or "08 Aug 26" style), and that each kept row contains at least one
of the given --keep tokens as an EXACT word match somewhere in that row (a
reference number is ideal; an exact amount string, as it literally appears
in the table, also works). A row's wrapped lines, above or below its date
line, belong to whichever date line is vertically nearest.

Usage:
    python redact_statement.py IN.pdf OUT.pdf --keep 14067855696 14067601959
    python redact_statement.py IN.pdf OUT.pdf --keep 11,242.45 --box 0:30,492,300,512

Scans every page by default and redacts each one that has a detectable
transaction table; pass --page to restrict to one page (0-indexed).

Summary redaction (on by default, --keep-summary to skip): on page 1 and
every page with a transaction table, blacks out every money amount
(digits with a 2-decimal tail, e.g. 1,65,912.46) and percentage outside the
kept rows. Bare integers (reward points, earnings) and amounts on other
pages aren't recognizable as personal figures, so cover those with --box
PAGE:x0,y0,x1,y1 (PDF points, 0-indexed page) after looking at a render.

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
MONTH = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?", re.I)
AMOUNT = re.compile(r"[₹`$]?-?\d[\d,]*\.\d{2}")
PERCENT = re.compile(r"\d+(\.\d+)?%")


def date_words(words):
    """Words that start a date: '28/08/2026', or the '08' of '08 Aug 26'."""
    out = []
    for i, w in enumerate(words):
        if DATE.fullmatch(w[4]):
            out.append(w)
        elif (re.fullmatch(r"\d{1,2}", w[4]) and i + 2 < len(words)
              and words[i + 1][5:7] == w[5:7] == words[i + 2][5:7]  # same block + line
              and MONTH.fullmatch(words[i + 1][4]) and re.fullmatch(r"\d{2}|\d{4}", words[i + 2][4])):
            out.append(w)
    return out


def redact_page(page, keep: set[str], match_counts: Counter):
    """Redact one page's transaction table. Returns the kept rows' rects, or
    None if this page has no detectable date column (e.g. a cover/summary page)."""
    words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word_no)
    dates = date_words(words)
    if len(dates) < 2:
        return None
    # Most transaction tables repeat the same left x-position for every row's
    # date; a handful of one-off dates elsewhere on the page (statement
    # period, due date) won't form a majority column.
    col_x, col_count = Counter(round(w[0]) for w in dates).most_common(1)[0]
    if col_count < 2:
        return None
    rows = sorted([w for w in dates if abs(w[0] - col_x) < 2], key=lambda w: w[1])

    gaps = sorted(b[1] - a[1] for a, b in zip(rows, rows[1:]))
    reach = gaps[len(gaps) // 2]  # median row pitch: how far a wrapped line can sit from its date line
    table = [w for w in words if w[0] >= col_x - 5
             and rows[0][1] - reach < w[1] < rows[-1][1] + reach]
    table_x1 = max(w[2] for w in table) + 2

    bands = [[] for _ in rows]
    for w in table:
        nearest = min(range(len(rows)), key=lambda i: abs(rows[i][1] - w[1]))
        bands[nearest].append(w)

    kept = []
    for band in bands:
        rect = pymupdf.Rect(min(w[0] for w in band) - 2, min(w[1] for w in band) - 1,
                            table_x1, max(w[3] for w in band) + 1)
        row_matches = {tok for w in band for tok in keep if tok == w[4]}
        match_counts.update(row_matches)
        if row_matches:
            kept.append(rect)
        else:
            page.add_redact_annot(rect, fill=(0, 0, 0))
    return kept


def redact_summary(page, kept_rects):
    """Black out money amounts and percentages outside the kept rows.
    Percentages only count on short lines (pie legends, spend breakdowns),
    not inside fine-print sentences like 'a fee of 1% of the amount'."""
    words = page.get_text("words")
    line_len = Counter(w[5:7] for w in words)
    for w in words:
        r = pymupdf.Rect(w[:4])
        pct = PERCENT.search(w[4]) and line_len[w[5:7]] <= 3
        if (AMOUNT.fullmatch(w[4]) or pct) and not any(r.intersects(k) for k in kept_rects):
            page.add_redact_annot(r + (-2, -1, 2, 1), fill=(0, 0, 0))


def redact(src: str, out: str, keep: set[str], page_no: int | None = None,
           summary: bool = True, boxes: list[tuple[int, pymupdf.Rect]] = ()) -> int:
    doc = pymupdf.open(src)
    pages = [doc[page_no]] if page_no is not None else list(doc)
    match_counts = Counter()

    kept = {}  # page number -> kept rects, for pages with a table
    for page in pages:
        result = redact_page(page, keep, match_counts)
        if result is not None:
            kept[page.number] = result

    if not kept:
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

    if summary:
        for n in {0, *kept}:
            redact_summary(doc[n], kept.get(n, []))
    for n, rect in boxes:
        doc[n].add_redact_annot(rect, fill=(0, 0, 0))

    for page in doc:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    doc.save(out, garbage=4, deflate=True)
    return sum(len(v) for v in kept.values())


def parse_box(s: str):
    page, coords = s.split(":")
    return int(page), pymupdf.Rect(*map(float, coords.split(",")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--keep", nargs="+", required=True, help="exact tokens (reference numbers or amounts, as they literally appear in the table) whose row stays visible")
    ap.add_argument("--page", type=int, default=None, help="0-indexed page to restrict to (default: scan all pages)")
    ap.add_argument("--keep-summary", action="store_true", help="don't redact amounts/percentages in the account summary")
    ap.add_argument("--box", action="append", type=parse_box, default=[], metavar="PAGE:x0,y0,x1,y1",
                    help="extra area to black out (PDF points, 0-indexed page); repeatable")
    args = ap.parse_args()

    kept_rows = redact(args.src, args.out, set(args.keep), args.page, not args.keep_summary, args.box)
    print(f"{args.out}: kept {kept_rows} row(s) visible across all matched pages", file=sys.stderr)
