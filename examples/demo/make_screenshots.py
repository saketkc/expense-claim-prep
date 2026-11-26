#!/usr/bin/env python3
"""Regenerate the README screenshots from made-up data (no real statements).

Builds a fake card statement and receipts for a fictional claimant, runs the
real scripts on them, and writes PNGs to docs/img/. Needs pymupdf, plus
neomutt or mutt for the email preview (nothing is sent: preview mode only).

    python examples/demo/make_screenshots.py
"""

import json
import os
import subprocess
import sys
import tempfile
from email.message import EmailMessage

import pymupdf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "img")
PY = sys.executable
W = tempfile.mkdtemp()
GREY = (0.45, 0.45, 0.45)


def text(page, x, y, s, size=9, bold=False, color=(0, 0, 0)):
    page.insert_text(
        (x, y), s, fontsize=size, fontname="hebo" if bold else "helv", color=color
    )


def statement(path):
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    text(p, 40, 50, "DEMO BANK  -  CREDIT CARD STATEMENT", 14, True)
    text(
        p,
        40,
        70,
        "Ananya Iyer   |   Card XXXX XXXX XXXX 1234   |   Statement date 12/11/2026",
        9,
        color=GREY,
    )
    text(p, 40, 105, "ACCOUNT SUMMARY", 10, True)
    for i, (k, v) in enumerate(
        [
            ("Previous balance", "48,210.55"),
            ("Purchases", "61,904.32"),
            ("Payments", "48,210.55"),
            ("Total amount due", "61,904.32"),
            ("Credit limit", "3,00,000.00"),
            ("Reward points earned", "1,204"),
        ]
    ):
        text(p, 40 + (i % 3) * 180, 125 + (i // 3) * 32, k, 8, color=GREY)
        text(p, 40 + (i % 3) * 180, 141 + (i // 3) * 32, v, 10, True)
    text(p, 40, 210, "TRANSACTIONS", 10, True)
    for x, h in [
        (40, "Date"),
        (110, "Ref. no."),
        (200, "Description"),
        (470, "Amount (INR)"),
    ]:
        text(p, x, 228, h, 8, True)
    rows = [
        ("14/10/2026", "70011223301", "GROCERY MART MUMBAI", "2,345.00"),
        ("16/10/2026", "70011223302", "TRAVELDESK FLIGHTS DELHI", "14,217.74"),
        ("17/10/2026", "70011223303", "STREAMFLIX SUBSCRIPTION", "649.00"),
        ("18/10/2026", "70011223304", "RIDEGO TRIPS BENGALURU", "598.19"),
        ("20/10/2026", "70011223305", "FASHION STORE ONLINE", "6,890.00"),
        ("22/10/2026", "70011223306", "RIDEGO TRIPS BENGALURU", "741.54"),
        ("25/10/2026", "70011223307", "PIZZA PLACE POWAI", "1,120.00"),
        ("28/10/2026", "70011223308", "ELECTRONICS HUB", "35,342.85"),
    ]
    for i, r in enumerate(rows):
        y = 248 + i * 22
        for x, s in zip((40, 110, 200, 470), r):
            text(p, x, y, s, 9)
    d.save(path)


def receipt(path, title, lines):
    d = pymupdf.open()
    p = d.new_page(width=595, height=842)
    text(p, 40, 60, title, 15, True)
    for i, s in enumerate(lines):
        text(p, 40, 95 + i * 18, s, 10)
    d.save(path)


def png(pdf, out, page=0, clip=None, dpi=110):
    pix = pymupdf.open(pdf)[page].get_pixmap(dpi=dpi, clip=clip)
    pix.save(out)


def side_by_side(left, right, out, labels):
    a, b = pymupdf.Pixmap(left), pymupdf.Pixmap(right)
    pad, top = 30, 40
    d = pymupdf.open()
    pg = d.new_page(
        width=a.width + b.width + 3 * pad, height=max(a.height, b.height) + top + pad
    )
    pg.draw_rect(pg.rect, color=None, fill=(1, 1, 1))
    pg.insert_image(pymupdf.Rect(pad, top, pad + a.width, top + a.height), pixmap=a)
    pg.insert_image(
        pymupdf.Rect(
            2 * pad + a.width, top, 2 * pad + a.width + b.width, top + b.height
        ),
        pixmap=b,
    )
    for x, s in ((pad, labels[0]), (2 * pad + a.width, labels[1])):
        pg.insert_text((x, 26), s, fontsize=16, fontname="hebo")
    pg.get_pixmap(dpi=72).save(out)


def terminal(lines, out, width=96):
    h = 30 + 15 * len(lines)
    d = pymupdf.open()
    p = d.new_page(width=width * 6.6 + 40, height=h)
    p.draw_rect(p.rect, color=None, fill=(0.11, 0.12, 0.14))
    for i, s in enumerate(lines):
        color = (0.55, 0.85, 0.55) if s.startswith("$") else (0.9, 0.9, 0.9)
        p.insert_text(
            (20, 24 + i * 15), s[:width], fontsize=11, fontname="cour", color=color
        )
    p.get_pixmap(dpi=110).save(out)


def run(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kw).stdout


def main():
    os.makedirs(OUT, exist_ok=True)
    st = os.path.join(W, "statement.pdf")
    red = os.path.join(W, "statement_REDACTED.pdf")
    statement(st)
    run(
        PY,
        f"{ROOT}/scripts/redact_statement.py",
        st,
        red,
        "--keep",
        "70011223302",
        "70011223304",
        "70011223306",
        "--box",
        "0:396,160,432,178",
    )  # reward points: a bare integer the summary pass skips
    clip = pymupdf.Rect(30, 30, 565, 440)
    png(st, f"{W}/before.png", clip=clip)
    png(red, f"{W}/after.png", clip=clip)
    side_by_side(
        f"{W}/before.png",
        f"{W}/after.png",
        f"{OUT}/redaction.png",
        [
            "Statement as downloaded",
            "After redact_statement.py --keep <3 refs> --box <points>",
        ],
    )

    tkt = os.path.join(W, "ticket.pdf")
    receipt(
        tkt,
        "E-TICKET  BOM -> BLR -> BOM",
        [
            "Passenger: ANANYA IYER",
            "PNR: ABC123 / DEF456",
            "Fare: INR 13,914.00   Agent fee: INR 303.74",
            "Charged to card: INR 14,217.74",
        ],
    )
    rides = []
    for n, (date, route, amt) in enumerate(
        [
            ("18/10/2026", "Hotel -> Conference venue", "598.19"),
            ("22/10/2026", "Conference venue -> Airport", "741.54"),
        ]
    ):
        rides.append(os.path.join(W, f"ride{n}.pdf"))
        receipt(
            rides[-1],
            "RideGo trip receipt",
            [f"Date: {date}", f"Trip: {route}", f"Total: INR {amt}"],
        )
    manifest = {
        "title": "Travel Claim - Example Conference, Bengaluru (16-22 Oct 2026)",
        "items": [
            {
                "date": "2026-10-16",
                "description": "Flights BOM-BLR-BOM (TravelDesk)",
                "amount": "14,217.74",
                "receipt": tkt,
                "proof": {"statement": "Demo Bank Oct 2026"},
            },
            {
                "date": "2026-10-18",
                "description": "RideGo: hotel to venue",
                "amount": "598.19",
                "receipt": rides[0],
                "proof": {"statement": "Demo Bank Oct 2026"},
            },
            {
                "date": "2026-10-22",
                "description": "RideGo: venue to airport",
                "amount": "741.54",
                "receipt": rides[1],
                "proof": {"statement": "Demo Bank Oct 2026"},
            },
        ],
        "statements": [{"label": "Demo Bank Oct 2026", "path": red, "pages": [0]}],
        "notes": ["Grant: DST-DEMO-2026-001, head Travel. Traveller: Ananya Iyer."],
    }
    mpath = os.path.join(W, "manifest.json")
    json.dump(manifest, open(mpath, "w"))
    combined = os.path.join(W, "Combined_Claim.pdf")
    run(PY, f"{ROOT}/scripts/build_combined_claim.py", mpath, combined)
    png(combined, f"{OUT}/combined_cover.png", clip=pymupdf.Rect(30, 30, 565, 330))

    # find_claimed.py against a fake sent folder
    sent = os.path.join(W, "Sent")
    os.makedirs(sent)
    old = os.path.join(W, "old_invoice.pdf")
    receipt(
        old,
        "INVOICE  CLOUD-0003",
        ["Billed to: Ananya Iyer", "Pro plan, Aug 2026", "Total: USD 118.00"],
    )
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = (
        "ananya.iyer@example.ac.in",
        "accounts@example.ac.in",
        "Reimbursement thread for DST-DEMO-2026-001",
    )
    m["Date"] = "Thu, 27 Aug 2026 10:06:55 +0530"
    m.set_content("Please find attached.")
    m.add_attachment(
        open(old, "rb").read(),
        maintype="application",
        subtype="pdf",
        filename="Claim-4_Cloud.pdf",
    )
    open(os.path.join(sent, "1.eml"), "wb").write(bytes(m))
    hits = run(
        PY,
        f"{ROOT}/scripts/find_claimed.py",
        "CLOUD-0003",
        "CLOUD-0004",
        input=os.path.join(sent, "1.eml") + "\n",
    ).splitlines()
    terminal(
        [
            "$ notmuch search --output=files 'from:ananya.iyer@example.ac.in' \\",
            "    | python scripts/find_claimed.py CLOUD-0003 CLOUD-0004",
            *hits,
            "",
            "# CLOUD-0003 went out on 27 Aug inside 'Claim-4_Cloud.pdf' -> don't claim it again.",
            "# CLOUD-0004 has no hit -> not in sent mail.",
        ],
        f"{OUT}/find_claimed.png",
        width=140,
    )

    # send_claim_mail.py preview (never sends)
    muttrc = os.path.join(W, "muttrc")
    open(muttrc, "w").write(
        'set from="Ananya Iyer <ananya.iyer@example.ac.in>"\nset realname="Ananya Iyer"\n'
    )
    body = os.path.join(W, "body.txt")
    open(body, "w").write(
        "Dear Accounts Section,\n\nPlease charge the attached claim to DST-DEMO-2026-001, head Travel: INR 15,557.47.\n\nThanks,\nAnanya\n"
    )
    job = os.path.join(W, "job.json")
    json.dump(
        {
            "to": ["accounts@example.ac.in"],
            "subject": "Re: Reimbursement thread for DST-DEMO-2026-001",
            "in_reply_to": "<thread-123@example.ac.in>",
            "body": body,
            "attachments": [combined],
            "muttrc": muttrc,
        },
        open(job, "w"),
    )
    try:
        prev = run(
            PY, f"{ROOT}/scripts/send_claim_mail.py", "preview", job
        ).splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"send_claim_mail preview failed (is neomutt installed?): {e}")
    prev = [
        l
        if not l.startswith("Nothing was sent. Rendered")
        else "Nothing was sent. Rendered message: /tmp/.../message.eml"
        for l in prev
    ]
    prev = [l.replace(job, "job.json").replace(f"{ROOT}/", "") for l in prev]
    terminal(
        ["$ python scripts/send_claim_mail.py preview job.json", *prev],
        f"{OUT}/send_preview.png",
        width=100,
    )
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
