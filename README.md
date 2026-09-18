# expense-claim-prep

A [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) that prepares a folder of receipts and credit-card statements for an expense claim. It matches travel/ride/flight receipts to statement transactions, permanently redacts every unrelated statement line (not just paints over it), tracks down missing payment-alert emails, and optionally generates a claim summary from your own claimant/bank-details template.

## What it does

- Inventories a folder of PDFs and classifies them as statements, receipts, or alert emails.
- Matches receipts to statement lines by date, amount, and (loosely) merchant name; flags ambiguous matches (duplicate amounts, FX charges, partial refunds) instead of guessing.
- Redacts every statement transaction except the ones you're claiming, using [PyMuPDF](https://pymupdf.readthedocs.io/) to actually remove the underlying text (`scripts/redact_statement.py`). A black box drawn over text with most PDF tools is still copy-pasteable; this isn't.
- Verifies the redaction by rendering the page and checking it, rather than assuming the script worked.
- Organizes the output into a numbered folder structure so the redacted statements and their matching receipts are easy to cross-reference.
- Fills gaps: if a receipt has no bank confirmation email, finds it and hands back a direct link/reference instead of a screenshot, using the Gmail connector (`https://mail.google.com/mail/u/0/#all/<messageId>`), Apple Mail on macOS (a `message://` link built from AppleScript), or mutt/notmuch (Message-ID + file path), in that order, and only takes a browser-automation screenshot if none of those apply. It confirms the account first and never touches a password or MFA code.
- Generates a claim summary (optional) from a claimant-info template you fill in yourself (name, contact, bank details, claim purpose) itemized against the matched transactions. Bank/tax details are deliberately kept out of the generated summary; they go straight into your institution's own secure form.
- Merges everything into one PDF (optional, `scripts/build_combined_claim.py`): a cover/index page, then per item [receipt, payment proof] back to back, with full statements attached at the end for items whose only proof is a statement line.

See [`SKILL.md`](./SKILL.md) for the full workflow and the boundaries it holds to (no guessing, no fabricated fields, no silently dropping refund lines).

## Using it with Claude Code

Clone (or symlink) this repo into your skills directory:

```bash
git clone https://github.com/saketkc/expense-claim-prep ~/.claude/skills/expense-claim-prep
```

Claude Code auto-discovers `SKILL.md`, and its frontmatter `description` is the trigger: just ask something like *"prepare my receipts and credit card statement for an expense claim, redact everything else"* and it activates on its own. No slash command needed.

## Using it with another agent (Cursor, Codex CLI, a plain chat model, etc.)

The auto-discovery/auto-trigger mechanism (`SKILL.md` frontmatter + Claude Code's `Skill` tool) is Claude-Code-specific. Everything else here is plain text and plain Python, so any coding agent, or you by hand, can follow it:

1. Point your agent at [`SKILL.md`](./SKILL.md) and tell it to follow that workflow for the folder of PDFs.
2. Both scripts run standalone with any Python plus [`pymupdf`](https://pypi.org/project/PyMuPDF/); no Claude Code required:
   ```bash
   pip install pymupdf
   python scripts/redact_statement.py statement.pdf statement_redacted.pdf --keep 14067855696 14067601959
   python scripts/build_combined_claim.py manifest.json Combined_Expense_Claim.pdf
   ```
3. The missing-payment-alert-email step tries, in order: a Gmail connector/MCP tool, Apple Mail via `osascript` (macOS only), mutt/notmuch, then browser automation as a last resort. An agent without any of these can just skip the step and find the alert emails manually.

## Files

```
SKILL.md                                     # the workflow + boundaries Claude (or any agent) follows
scripts/redact_statement.py                  # standalone PDF redaction tool (no Claude Code dependency)
scripts/build_combined_claim.py              # merges matched receipts + proof into one submission PDF
examples/claimant_info.example.yaml          # blank template for claimant + bank details
examples/claim_manifest.example.json         # example manifest for build_combined_claim.py
```

## A word on the redaction script

`redact_statement.py` finds each transaction row by a repeated date column and redacts every row that doesn't contain an exact match for one of your `--keep` tokens (reference numbers are the reliable anchor; exact amounts work if the statement has no reference column). It fails closed: it refuses to save if a keep-token matches zero rows or more than one, rather than silently producing a wrong redaction. It only works on statements with live text (not scanned images), and only redacts the pages it scans — see `SKILL.md` for the full list of what it does and doesn't cover.

**Always render the output and look at it before submitting anything.** This tool is a starting point for a financial document going to a third party, not a black box to trust blindly.

## License

MIT. See [LICENSE](./LICENSE).

## Credits

Prototyped with [claude.ai](https://claude.ai/)
