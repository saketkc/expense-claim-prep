#!/usr/bin/env python3
"""Check whether receipts were already claimed: search the PDF attachments of
mail you sent for invoice numbers, PNRs, card reference numbers or amounts.

Subject searches miss claims (a past claim may be titled anything, and its
receipts may be renamed, zipped or merged into one combined PDF), so this
reads the attachments themselves.

Reads message file paths (Maildir/.eml) on stdin, e.g. with notmuch:
    notmuch search --output=files 'from:me@example.org and date:2025-06-01..' \\
        | python find_claimed.py INV-0004 ABC123 98765432101

or a plain Maildir:
    find ~/Mail/Sent -type f | python find_claimed.py INV-0004

Prints one line per (message, attachment) that contains any token:
    date | to | subject | attachment | tokens found
Tokens match case-insensitively as plain substrings of the attachment's
filename or its pdftotext output (zip attachments are opened too). No hits
means "not found in sent mail", not "never claimed": claims made through a
portal, on paper or from another mailbox won't show up.

Needs only the standard library and `pdftotext` (poppler).
"""

import email
import io
import subprocess
import sys
import tempfile
import zipfile
from email import policy


def pdf_text(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
        t.write(data)
        t.flush()
        return subprocess.run(
            ["pdftotext", "-layout", t.name, "-"], capture_output=True, text=True
        ).stdout


def attachments(msg):
    for part in msg.walk():
        name = part.get_filename()
        data = part.get_payload(decode=True) if name else None
        if not data:
            continue
        if name.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                for inner in z.namelist():
                    if inner.lower().endswith(".pdf"):
                        yield f"{name}/{inner}", z.read(inner)
            except zipfile.BadZipFile:
                pass
        else:
            yield name, data


def main(tokens):
    tokens = [t.lower() for t in tokens]
    seen = set()  # the same attachment is often re-sent down a thread
    for path in sys.stdin.read().split("\n"):
        if not path:
            continue
        try:
            msg = email.message_from_binary_file(
                open(path, "rb"), policy=policy.default
            )
        except (OSError, ValueError):
            continue
        for name, data in attachments(msg):
            key = (name, len(data), msg["Message-ID"])
            if key in seen:
                continue
            seen.add(key)
            text = name + (
                "\n" + pdf_text(data) if name.lower().endswith(".pdf") else ""
            )
            hits = [t for t in tokens if t in text.lower()]
            if hits:
                print(
                    f"{msg['Date']} | {msg['To']} | {msg['Subject']} | {name} | {' '.join(hits)}"
                )


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.stdin.isatty():
        sys.exit(__doc__)
    main(sys.argv[1:])
