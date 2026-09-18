---
name: expense-claim-prep
description: This skill should be used when the user asks to prepare receipts and credit card statements for an expense claim or reimbursement, wants unrelated transactions blacked out (redacted) on a credit card statement PDF before submitting it, asks to match travel/Uber/flight receipts against statement transactions and track down missing payment-alert emails, or wants everything merged into one combined PDF (receipt + payment proof per item) for submission.
---

Prepare a folder of receipts and redacted credit card statements for filing an expense claim, keeping only the transactions the user is actually claiming visible.

## Goal

Given a pile of PDFs in a folder (credit card statements, flight/Uber/hotel receipts, payment-confirmation emails) produce a submission-ready folder where:
- statements have every line **except** the claimed transactions permanently blacked out (not just visually covered — actually removed from the PDF content),
- receipts are matched to statement lines and organized/renamed for easy cross-referencing,
- gaps are called out instead of guessed at (missing receipts, refunds, transactions on a card with no statement in the folder),
- optionally, everything is merged into one combined PDF for submission: cover/index page, then per item [receipt, payment proof] back to back, with any full statements attached at the end.

## Boundaries

- Does **not** guess which card an unmatched transaction belongs to — ask or flag it.
- Does **not** silently drop a refund/credit line near a claimed charge — leave it visible and flag it, since the reimbursement office may need to net it out.
- Does **not** cover software other than PDF word-position redaction with PyMuPDF (`pymupdf`) — that's the one reliable way to guarantee redacted text isn't recoverable by copy-paste.
- Does **not** read the user's inbox to compile unrelated financial history — only searches Gmail for the specific alert emails needed to fill a receipt gap, and only after the user confirms which account.
- Does **not** invent claimant/bank details. Only fields the user actually supplied go in the claim summary; a missing field stays visibly blank (e.g. `[NOT PROVIDED]`), never a guess.

## Default workflow

1. **Inventory.** `ls`/`pdftotext -layout` every PDF in the folder. Classify into: statements (has a per-transaction table), receipts (ride/flight/hotel confirmations), and payment-alert emails saved as PDF.
2. **Extract statement transactions.** Use `pdftotext -layout` first for a quick read. For redaction you need exact word coordinates — use PyMuPDF (`page.get_text("words")`), not text extraction, since layouts vary per bank.
3. **Match receipts to statement lines** by date + amount (and merchant name loosely — Uber/airline names get mangled by payment processors). Note the statement's reference number for each match — it's the reliable per-row anchor for redaction.
4. **Flag before redacting:**
   - a receipt with no matching statement line (different card, or the card's statement isn't in the folder),
   - a statement line that looks claimable but has no receipt,
   - refunds/credits adjacent to a claimed charge,
   - two receipts/lines with the same date and amount (can't tell them apart on date+amount alone — need the reference number or another distinguishing detail),
   - foreign-currency charges (the statement's INR/USD/etc. amount includes a markup/FX fee the receipt won't show — flag the mismatch instead of silently picking one number),
   - a charge that's a partial refund or split payment rather than a clean one-line match.
   Surface these to the user rather than deciding unilaterally what counts as "related."
5. **Redact.** Run `scripts/redact_statement.py` per statement, passing the reference numbers (or exact amounts, if a statement layout has no reference-number column) to keep visible. It:
   - scans every page for a transaction table (a repeated date column), not just page 1,
   - bands each table into rows and redacts every row that doesn't contain an exact-word match for a kept token,
   - uses `page.add_redact_annot` + `apply_redactions()`, which removes the underlying text objects on that page — it does not touch other pages, embedded images, or PDF metadata, and it can't redact a scanned-image table (there's no text object to remove),
   - fails closed: raises instead of saving if a kept token matches zero rows (typo) or more than one row (ambiguous — use a more specific token, e.g. the reference number instead of a repeating amount).
6. **Verify, don't assume.** Render the redacted page(s) to PNG (`pdftoppm -r 90 -png`) and actually look — check no row bled into a neighboring row, and that redacted rows produce no `pdftotext` output. If the statement's table is a scanned image rather than live text, this script can't help at all; rasterize/crop the whole page instead. Redaction bugs are silent failures; always re-check visually before handing the file back.
7. **Organize the output folder**, e.g.:
   ```
   1_Statements_redacted/
   2_Receipts_matched_to_statements/
   3_Receipts_other_card_<bank/last4>/   # if a second card's receipts have no statement
   4_Receipts_not_on_statements/         # receipt exists, no matching charge found
   ```
   Rename receipts `YYYY-MM-DD_Merchant_Amount.pdf` so the reimbursement office can eyeball the correspondence.
8. **Missing payment-alert emails.** If a receipt has no bank confirmation and the user says it might be in Gmail: confirm the exact account first (don't guess from a typo'd address or from whichever account the browser happens to be signed into — a wrong guess here means digging through someone else's inbox). Then search `from:<bank-alert-address> <amount>`, open the exact message matching the date/amount, screenshot it, and save alongside the matched receipt. Never enter a password, OTP, or MFA code yourself — if the browser isn't already signed into the confirmed account, ask the user to sign in themselves. Gmail groups near-duplicate alerts (failed-attempt amounts before the final charge) into one thread — always confirm the exact amount before screenshotting, not just the first message in the thread. If no matching alert exists, say so; don't leave the gap unmentioned.
9. **Claimant/bank details (optional).** Most reimbursement forms need the same handful of fields regardless of institution: claimant name/ID/contact, bank account for the transfer, and a claim purpose/cost-center. Rather than hardcode one institution's form:
   - Check whether the claim folder already has a filled-in info file (any name, YAML/JSON/text). If not, offer `examples/claimant_info.example.yaml` as a starting point — the user copies it into the claim folder and fills it in (not into the skill directory; it holds bank details and PII).
   - Once filled, generate a plain `Claim_Summary.md` in the output folder with the claimant fields and an itemized table of the matched transactions (date, merchant/purpose, amount, currency, payment method or card last 4, receipt filename). **Leave `bank_details` and `tax_id` out of this file** — those go directly into the institution's own secure form/portal, not into a document that also lists travel details and may get forwarded or attached elsewhere. Say explicitly that you omitted them and why, so the user isn't looking for them later.
   - If the user gives details inline in chat instead of a file, use those directly — don't insist on the file.
10. **Combine into one submission PDF (optional).** If the user wants a single file instead of a folder: build a JSON manifest (see `examples/claim_manifest.example.json`) listing each item's date/description/amount/receipt/proof — `proof` is a path for an inline receipt/alert/screenshot, or `{"statement": "<label>"}` for an item whose only proof is a statement line (that item gets a one-page pointer instead, and the labeled statement must be listed under `statements` to be attached in full at the end). Run `scripts/build_combined_claim.py manifest.json out.pdf`, then **render it and actually look** — same discipline as step 6, this is the document that gets submitted. It writes text with PDF base-14 fonts (Latin-1 only) — use `->` and `-`, not arrow/en-dash characters, or they silently render as a middot.

## Notes

- PyMuPDF isn't preinstalled; use a throwaway venv, e.g.:
  ```bash
  V=$(mktemp -d) && uv venv -q "$V" && uv pip install -q --python "$V/bin/python" pymupdf
  "$V/bin/python" scripts/redact_statement.py IN.pdf OUT.pdf --keep 12345
  ```
- `scripts/redact_statement.py` assumes a table with a per-row date in a fixed column and a reference-number (or other unique per-row token) somewhere in that row — true for ICICI-style statements. A statement without a stable per-row anchor, or whose table is a scanned image, needs a different approach (see step 6).
- Redaction removes text objects from the pages it processes; it doesn't scrub PDF metadata (author, title, etc.) or embedded thumbnails. If the statement PDF's metadata itself contains sensitive info, strip it separately (`exiftool -all= FILE.pdf` or similar) before sharing.
- `examples/claimant_info.example.yaml` is a template, not a data store. The filled copy contains bank account and contact details — treat it like the receipts (local to the claim folder, not committed or synced elsewhere, and never copied wholesale into `Claim_Summary.md`).
- `scripts/build_combined_claim.py` uses the same throwaway venv as `redact_statement.py` (both need `pymupdf`):
  ```bash
  "$V/bin/python" scripts/build_combined_claim.py manifest.json Combined_Expense_Claim.pdf
  ```
  The manifest's paths are resolved relative to the working directory the script is run from, not the manifest's own location.
