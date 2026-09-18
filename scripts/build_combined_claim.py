#!/usr/bin/env python3
"""Merge matched receipts + payment proof into one submission-ready PDF, in
the order: cover/index page, then per item [receipt, payment proof] back to
back, then any full statements attached at the end.

Takes a JSON manifest (see examples/claim_manifest.example.json) rather than
hardcoded paths, so it's reusable across claims. An item's "proof" is either
a path to a PDF/JPG/PNG to insert inline, or {"statement": "<label>"} for an
item whose only proof is a credit-card-statement line -- that item gets a
one-page pointer instead, and the labeled statement must appear in
"statements" to be attached in full at the end.

Usage:
    python build_combined_claim.py manifest.json out.pdf

Text is written with PDF base-14 fonts (helv/hebo), which only cover
Latin-1 -- avoid arrows/en-dashes/curly quotes in the manifest ("->" and "-"
render; "→" and "–" silently turn into a middot).
"""
import argparse
import json

import pymupdf

A4 = (595, 842)


def text_page(doc, lines, title=None):
    page = doc.new_page(width=A4[0], height=A4[1])
    y = 60
    if title:
        page.insert_text((50, y), title, fontsize=15, fontname="hebo")
        y += 30
    for line, size, bold in lines:
        page.insert_text((50, y), line, fontsize=size, fontname="hebo" if bold else "helv")
        y += size + 8


def image_page(doc, img_path):
    page = doc.new_page(width=A4[0], height=A4[1])
    margin = 40
    rect = pymupdf.Rect(margin, margin, A4[0] - margin, A4[1] - margin)
    page.insert_image(rect, filename=img_path, keep_proportion=True)


def insert_proof(out, proof, statement_labels):
    if isinstance(proof, dict):
        label = proof["statement"]
        if label not in statement_labels:
            raise SystemExit(f"Item references statement '{label}' which isn't listed in \"statements\".")
        return ("STATEMENT", label)
    if proof.lower().endswith((".jpg", ".jpeg", ".png")):
        image_page(out, proof)
    else:
        out.insert_pdf(pymupdf.open(proof))
    return None


def build(manifest_path: str, out_path: str) -> int:
    manifest = json.load(open(manifest_path))
    items = manifest["items"]
    statements = manifest.get("statements", [])
    statement_labels = {s["label"] for s in statements}
    title = manifest.get("title", "Expense Claim - Combined Receipts and Payment Proof")
    notes = manifest.get("notes", [])  # free-text lines for exclusions/flags, shown on the cover page

    out = pymupdf.open()

    total = sum(float(str(item["amount"]).replace(",", "")) for item in items)
    lines = [("Item    Date          Description                                   Amount", 10, True)]
    for i, item in enumerate(items, 1):
        marker = " *" if isinstance(item["proof"], dict) else ""
        lines.append((f"{i:>2}.     {item['date']:<13} {item['description']:<42} {item['amount']:>10}{marker}", 9, False))
    lines.append(("", 10, False))
    lines.append((f"Grand total: {manifest.get('currency', 'INR')} {total:,.2f}", 11, True))
    if any(isinstance(item["proof"], dict) for item in items):
        lines.append(("", 10, False))
        lines.append(("* Payment proof for this item is the credit card statement line, not a", 8, False))
        lines.append(("  separate alert -- see the attached statement in the last section.", 8, False))
    for note in notes:
        lines.append(("", 10, False))
        lines.append((note, 8, False))
    text_page(out, lines, title=title)

    for i, item in enumerate(items, 1):
        out.insert_pdf(pymupdf.open(item["receipt"]))
        pointer = insert_proof(out, item["proof"], statement_labels)
        if pointer:
            _, label = pointer
            text_page(out, [
                (f"Item {i}: {item['description']}", 11, True),
                (f"{item['date']}  --  {item['amount']}", 10, False),
                ("", 10, False),
                (f"Payment proof: {label} credit card statement", 10, False),
                ("(attached in full at the end of this document)", 10, False),
            ])

    if statements:
        text_page(out, [
            ("Statements below are attached in full. Every transaction except the", 10, False),
            ("ones in this claim should already be redacted -- verify before sending.", 10, False),
        ], title="Payment Proof: Credit Card Statements")
        for s in statements:
            text_page(out, [(s["label"], 12, True)])
            out.insert_pdf(pymupdf.open(s["path"]))

    out.save(out_path, garbage=4, deflate=True)
    return out.page_count


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", help="JSON manifest (see examples/claim_manifest.example.json)")
    ap.add_argument("out", help="output PDF path")
    args = ap.parse_args()

    pages = build(args.manifest, args.out)
    print(f"{args.out}: {pages} pages")
