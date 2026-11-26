---
name: expense-claim-prep
description: This skill should be used when the user asks to prepare receipts and credit card statements for an expense claim or reimbursement, wants unrelated transactions blacked out (redacted) on a credit card statement PDF before submitting it, asks to match travel/Uber/flight receipts against statement transactions and track down missing payment-alert emails, or wants everything merged into one combined PDF (receipt + payment proof per item) for submission, or wants claimable items found in their mailbox, checked against what they already claimed, assigned to a grant/budget head, and emailed to accounts staff after a preview.
---

Prepare a folder of receipts and redacted credit card statements for filing an expense claim, keeping only the transactions the user is actually claiming visible.

## Goal

Given a pile of PDFs in a folder (credit card statements, flight/Uber/hotel receipts, payment-confirmation emails) produce a submission-ready folder where:
- statements have every line **except** the claimed transactions permanently blacked out (not just visually covered, but actually removed from the PDF content),
- receipts are matched to statement lines and organized/renamed for easy cross-referencing,
- gaps are called out instead of guessed at (missing receipts, refunds, transactions on a card with no statement in the folder),
- optionally, everything is merged into one combined PDF for submission: cover/index page, then per item [receipt, payment proof] back to back, with any full statements attached at the end.

## Boundaries

- Does **not** guess which card an unmatched transaction belongs to; it asks or flags it instead.
- Does **not** silently drop a refund/credit line near a claimed charge; it leaves it visible and flags it, since the reimbursement office may need to net it out.
- Does **not** cover software other than PDF word-position redaction with PyMuPDF (`pymupdf`), the one reliable way to guarantee redacted text isn't recoverable by copy-paste.
- Does **not** read the user's inbox to compile unrelated financial history; it only searches Gmail for the specific alert emails needed to fill a receipt gap, and only after the user confirms which account.
- Does **not** send email on its own. It drafts; it sends only through `scripts/send_claim_mail.py`, after the user has seen that email's preview and approved it explicitly in this conversation.
- Does **not** claim bookings for other passengers, cancelled bookings, or anything the user calls personal. Those are kept as evidence in `cancelled_not_claimed/` or `personal_not_claimed/`, not deleted.
- Does **not** invent claimant/bank details. Only fields the user actually supplied go in the claim summary; a missing field stays visibly blank (e.g. `[NOT PROVIDED]`), never a guess.

## Default workflow

1. **Inventory.** If the user starts from their mailbox rather than a folder ("find my claimable stuff"), first search mail for the usual sources: travel-agent e-tickets, ride receipts, card transaction alerts, and software and shop invoices. Group them by trip (outbound date to return date) or by category, and save them as PDFs into the claim folders (step 8 covers how). Then continue as below. `ls`/`pdftotext -layout` every PDF in the folder. Classify into: statements (has a per-transaction table), receipts (ride/flight/hotel confirmations), and payment-alert emails saved as PDF.
2. **Extract statement transactions.** Use `pdftotext -layout` first for a quick read. For redaction you need exact word coordinates: use PyMuPDF (`page.get_text("words")`), not text extraction, since layouts vary per bank.
3. **Match receipts to statement lines** by date + amount (and merchant name loosely, since Uber/airline names get mangled by payment processors). Note the statement's reference number for each match; it's the reliable per-row anchor for redaction.
4. **Flag before redacting:**
   - a receipt with no matching statement line (different card, or the card's statement isn't in the folder),
   - a statement line that looks claimable but has no receipt,
   - refunds/credits adjacent to a claimed charge,
   - two receipts/lines with the same date and amount (can't tell them apart on date+amount alone; need the reference number or another distinguishing detail),
   - foreign-currency charges (the statement's INR/USD/etc. amount includes a markup/FX fee the receipt won't show; flag the mismatch instead of silently picking one number),
   - a charge that's a partial refund or split payment rather than a clean one-line match.
   Surface these to the user rather than deciding unilaterally what counts as "related."
5. **Redact.** Run `scripts/redact_statement.py` per statement, passing the reference numbers (or exact amounts, if a statement layout has no reference-number column) to keep visible. It:
   - scans every page for a transaction table (a repeated date column), not just page 1,
   - bands each table into rows and redacts every row that doesn't contain an exact-word match for a kept token,
   - uses `page.add_redact_annot` + `apply_redactions()`, which removes the underlying text objects on that page; it does not touch other pages, embedded images, or PDF metadata, and it can't redact a scanned-image table (there's no text object to remove),
   - fails closed: raises instead of saving if a kept token matches zero rows (typo) or more than one row (ambiguous; use a more specific token, e.g. the reference number instead of a repeating amount),
   - recognizes `28/08/2026`-style and `08 Aug 26`-style (SBI) date columns, and attaches a row's wrapped description lines (above or below the date line) to the nearest date row,
   - also redacts the account summary by default: every money amount (`1,65,912.46`-style) and every short-line percentage (spend breakdowns) on page 1 and on table pages, outside the kept rows. Bare integers (reward points, earnings) and the savings/benefits tables on other pages aren't caught. After rendering, cover them with `--box PAGE:x0,y0,x1,y1` (PDF points, 0-indexed page; get coordinates from `page.get_text("words")`). Box each value separately so the labels stay readable. Leave visible the statement date, due date, name and masked card number. A pie chart loses its percentages but its slices still show; box it if that matters. `--keep-summary` turns the summary pass off.
6. **Verify, don't assume.** Render the redacted page(s) to PNG (`pdftoppm -r 90 -png`; if it hangs on a malformed PDF, as SBI statements can, use PyMuPDF's `page.get_pixmap(dpi=80).save(...)`) and actually look: check no row bled into a neighboring row, and that redacted rows produce no `pdftotext` output. If the statement's table is a scanned image rather than live text, this script can't help at all; rasterize/crop the whole page instead. Redaction bugs are silent failures; always re-check visually before handing the file back.
7. **Organize the output folder**, e.g.:
   ```
   1_Statements_redacted/
   2_Receipts_matched_to_statements/
   3_Receipts_other_card_<bank/last4>/   # if a second card's receipts have no statement
   4_Receipts_not_on_statements/         # receipt exists, no matching charge found
   ```
   Rename receipts `YYYY-MM-DD_Merchant_Amount.pdf` so the reimbursement office can eyeball the correspondence.

   **Where fetched files go:** save anything pulled from mail (receipts, rendered emails, alerts) without asking, into `<claims root>/YYYY_MM/YYYY-MM-DD/`, keyed by the trip's start date (e.g. `Expense_Claims/2026_10/2026-10-09/`). The claims root is the folder the user names, or its parent if the named folder is already a `YYYY_MM` folder. Create the folders as needed. Never overwrite or move files the user saved there themselves.
8. **Missing payment-alert emails.** If a receipt has no bank confirmation and the user says it might be in their mail: confirm the exact account first (don't guess from a typo'd address or from whichever account is signed in by default; a wrong guess here means digging through someone else's inbox), then try backends in this order. **Prefer a direct link/reference over a screenshot in every case.** It's cheaper, and the user can always screenshot it themselves if they need a static image.
   - **Gmail connector/MCP tool**, if available: search `from:<bank-alert-address> <amount>`, confirm the exact date/amount match (a bank alert thread groups near-duplicate amounts, including failed-attempt charges before the final one, so don't grab the first hit), and hand back `https://mail.google.com/mail/u/0/#all/<messageId>` from the search result. This is the fastest and most reliable backend since it uses Gmail's own server-side index; prefer it whenever the account is Gmail and the tool is available.
   - **Apple Mail (macOS), via `osascript`**, if no Gmail connector applies (other providers, or Gmail synced as an IMAP account in Mail.app): enumerate `every mailbox of account "<name>"` and search a small, specific mailbox first (Inbox, or a labeled folder). A `whose` filter over a huge mailbox (a Gmail "All Mail" with years of history is the classic case) can take minutes or hang; if a search doesn't return quickly, stop and narrow it (specific folder, tighter subject match) rather than waiting indefinitely. On a match, read `message id of <msg>` (the RFC `Message-ID` header) and build `message://%3c<url-encoded message id>%3e`; opening that (`open "message://..."`) jumps Mail.app straight to it. Confirmed to work for enumerating accounts/mailboxes and extracting message IDs; whether a given search finishes quickly depends entirely on mailbox size, so budget for that per-search rather than assuming it's instant.
   - **mutt / local Maildir**, if neither of the above applies: if `notmuch` is set up (the common mutt pairing), `notmuch search --output=files 'from:<bank-alert-address> and <amount>'`; otherwise `grep -rl` the Maildir for the sender and amount. From the matched file, read the `Message-ID:` header and give the user both that ID (usable inside mutt as a limit pattern, `~i "<message-id>"`) and the raw file path, since mutt has no clickable-link concept and this is the closest equivalent. Tested against a live notmuch setup:
     - **Check index freshness first.** `notmuch search --sort=newest-first --limit=1 '*'`. If the newest result is older than the trip, the Maildir may still be current but unindexed; `notmuch new` fixes it (it only updates notmuch's own database, not the mail, but a large mailbox can take minutes).
     - Ticket/ride receipts are often HTML-only emails, with no PDF attachment (travel-agent e-tickets, Uber). Parse them with Python's `email` module (`policy.default`, `get_body(('html','plain'))`). Save a PDF by writing the HTML (with a From/Date/Subject/Message-ID header block prepended) to a file and printing it with headless Chrome: `"<Chrome binary>" --headless=new --no-pdf-header-footer --print-to-pdf=OUT.pdf file://IN.html`. WeasyPrint can fail on macOS for lack of `libgobject`.
     - Uber sends several receipt emails per trip: "Failed payment" versions first, then a final one. Use the latest email without "Failed payment", and note that one ride can be charged as two card transactions (match the sum). A card alert that doesn't equal any receipt total (e.g. an authorization amount) gets flagged, not silently matched.
     - Travel-agent inboxes can hold bookings for other passengers made from the same account. Filter by passenger name, and for rebookings, keep the latest booking that wasn't cancelled (look for a matching "Cancellation" email per PNR).
   - **Only fall back to browser automation** (find the message, screenshot it, save alongside the matched receipt) when none of the above apply. Never enter a password, OTP, or MFA code yourself; if the browser isn't already signed into the confirmed account, ask the user to sign in themselves.
   - If no matching alert exists in any backend, say so; don't leave the gap unmentioned, and don't fabricate a message ID or link for a message you didn't actually find.
9. **Claimant/bank details (optional).** Most reimbursement forms need the same handful of fields regardless of institution: claimant name/ID/contact, bank account for the transfer, and a claim purpose/cost-center. Rather than hardcode one institution's form:
   - Check whether the claim folder already has a filled-in info file (any name, YAML/JSON/text). If not, offer `examples/claimant_info.example.yaml` as a starting point: the user copies it into the claim folder and fills it in (not into the skill directory; it holds bank details and PII).
   - Once filled, generate a plain `Claim_Summary.md` in the output folder with the claimant fields and an itemized table of the matched transactions (date, merchant/purpose, amount, currency, payment method or card last 4, receipt filename). **Leave `bank_details` and `tax_id` out of this file.** Those go directly into the institution's own secure form/portal, not into a document that also lists travel details and may get forwarded or attached elsewhere. Say explicitly that you omitted them and why, so the user isn't looking for them later.
   - If the user gives details inline in chat instead of a file, use those directly; don't insist on the file.
10. **Combine into one submission PDF (optional).** If the user wants a single file instead of a folder: build a JSON manifest (see `examples/claim_manifest.example.json`) listing each item's date/description/amount/receipt/proof, where `proof` is a path for an inline receipt/alert/screenshot, or `{"statement": "<label>"}` for an item whose only proof is a statement line (that item gets a one-page pointer instead, and the labeled statement must be listed under `statements` to be attached in full at the end). A `receipt` (or `proof`) can be a list of files merged in order, e.g. ticket + boarding passes, and JPG/PNG screenshots become image pages. A statement can set `"pages": [0, 1]` to attach only the summary page and the pages with claimed lines, not the whole statement. Run `scripts/build_combined_claim.py manifest.json out.pdf`, then **render it and actually look**: same discipline as step 6, this is the document that gets submitted. It writes text with PDF base-14 fonts (Latin-1 only): use `->` and `-`, not arrow/en-dash characters, or they silently render as a middot.

11. **Check nothing was claimed already. Do this before drafting anything.** Email subjects aren't reliable: past claims go out under many subjects, and receipts get renamed, zipped or merged into one PDF. Search the *attachments* of the user's sent mail for each item's invoice number, PNR, card reference number or exact amount:
    ```bash
    notmuch search --output=files 'from:<user address> and date:<a year back>..' \
      | python scripts/find_claimed.py <invoice-no> <PNR> <ref-no> ...
    ```
    `find_claimed.py` reads PDF attachments (including inside zips) with `pdftotext`. A hit can be a false positive: a cover page that says "already claimed, not included: X" mentions X too. So open the hit before deciding. No hit means "not in this sent folder", not "never claimed"; ask about portals or paper claims if the amount is large. Move anything already claimed into `already_claimed/` with an `ALREADY_CLAIMED_` prefix so it can't be re-sent.

12. **Trips.**
    - Keep only the claimant's own tickets: travel-agent logins often book for colleagues too.
    - For a rebooking, claim the booking actually flown and keep the cancelled one in `cancelled_not_claimed/`. Look for its refund on the statement, and flag a leg that was never cancelled or refunded. If the wrong tickets were already sent to a host, send a short correction with the right ones.
    - Ask what each trip was for (event, meeting, host) when the mail doesn't say. Invitations from the event's organisers usually settle it. Ask whether the host reimburses travel; if so, the claim goes to them, not to a grant.
    - Ask before claiming anything that may be personal, such as one leg of a multi-stop trip, or a consumer subscription. The user decides; don't infer it from the merchant.
    - Collect boarding passes from airline check-in emails. App screenshots (JPG/PNG) can go straight into a combined PDF as image pages.

13. **Which amount to claim.**
    - Claim what the card was actually charged, so travel-agent and payment-gateway fees and forex markup are included. Note the fare and the fee separately when they differ.
    - If the invoice total and the card charge differ for no clear reason, claim the invoice amount, rename the alert `..._MISMATCH`, and tell the user.
    - If an invoice is billed to someone else's name or address (marketplace invoices sometimes are), use a document in the claimant's name instead, such as the order summary, and say so.

14. **Choosing the grant or budget head (optional).** If the user keeps funding data (balances per grant and head, end dates), choose for each claim using these default rules, unless they've written their own:
    - Travel is paid only from a travel head. Anything else non-equipment can come from contingency.
    - Spend the money that expires soonest first. Keep flexible money (funds that can move between heads) for last.
    - Don't split one claim across grants unless accounts asks.
    - Check the head still has enough after this claim *and* after claims already sent but not yet reimbursed. Those aren't in the grant system yet, so ask whether earlier claims have been processed.

    Show a table before building anything: item → grant → head → amount → balance left, with a one-line reason each. Put the grant and head on the claim's cover page and in the email. If no rule settles a case, ask.

15. **Sending (only when asked).**
    - **Choose the recipients.** Use `claim_contacts` from the claimant info file, matching the claim's grant code or category, then falling back to `default`. If there are none, suggest the people who usually receive the user's claims, and save them to the file only after the user confirms:
      ```bash
      notmuch address --output=recipients --output=count --deduplicate=address \
        'from:<user address> and (subject:reimburs* or subject:claim)' | sort -rn | head
      ```
      Then find that contact's latest thread for the grant: `notmuch search --sort=newest-first 'to:<contact> and subject:"<thread_subject>"'`. Never guess a recipient from a similar name. A host-reimbursed claim goes to the host's organiser, not to the accounts office.
    - **Write a job file.** List the recipients, the subject, the body file and the attachments. Reply in the existing claim thread (`in_reply_to` and `references` from that thread's latest message), keeping its Cc list. Start the body with what to charge to: grant, head and amount.
    - **Preview:** `python scripts/send_claim_mail.py preview job.json`. This builds the exact MIME message without sending it and prints the headers, body, attachments, and **what is being claimed** (read from each claim PDF's cover page). Show this preview to the user.
    - **Send:** run `send job.json --confirm <code>`, but only after the user says to send that specific email. The code is a hash of the job, the body and the attachments, so any edit after the preview needs a new preview. Send mode points `sendmail` at `/usr/bin/false`, so a missing SMTP setting fails instead of queueing mail locally.
    - Don't improvise a dry run with a `sendmail="cat > file"`-style setting. mutt rejects shell metacharacters, falls back to the system sendmail, and really queues the mail.
    - **Check it went.** Afterwards, parse the copy in the Sent folder: recipients, the In-Reply-To header, and the number of attachments.
    - **Record it** as pending against the grant until it's reimbursed.
    - **Extra redaction for outside recipients.** When proof goes outside the user's institution (for example to a host), also black out the spend-breakdown chart, the reward points on each kept row, and any credit-limit figures, using `--box` or extra redaction annotations. Render each page and check it.

## Notes

- PyMuPDF isn't preinstalled; use a throwaway venv, e.g.:
  ```bash
  V=$(mktemp -d) && uv venv -q "$V" && uv pip install -q --python "$V/bin/python" pymupdf
  "$V/bin/python" scripts/redact_statement.py IN.pdf OUT.pdf --keep 12345
  ```
- `scripts/redact_statement.py` assumes a table with a per-row date in a fixed column and a reference-number (or other unique per-row token) somewhere in that row. That's true for ICICI-style statements. For SBI-style statements with no reference column, keep by the exact INR amount (e.g. `--keep 11,242.45`). A statement without a stable per-row anchor, or whose table is a scanned image, needs a different approach (see step 6).
- Redaction removes text objects from the pages it processes; it doesn't scrub PDF metadata (author, title, etc.) or embedded thumbnails. If the statement PDF's metadata itself contains sensitive info, strip it separately (`exiftool -all= FILE.pdf` or similar) before sharing.
- `examples/claimant_info.example.yaml` is a template, not a data store. The filled copy contains bank account and contact details; treat it like the receipts (local to the claim folder, not committed or synced elsewhere, and never copied wholesale into `Claim_Summary.md`).
- `scripts/build_combined_claim.py` uses the same throwaway venv as `redact_statement.py` (both need `pymupdf`):
  ```bash
  "$V/bin/python" scripts/build_combined_claim.py manifest.json Combined_Expense_Claim.pdf
  ```
  The manifest's paths are resolved relative to the working directory the script is run from, not the manifest's own location.
