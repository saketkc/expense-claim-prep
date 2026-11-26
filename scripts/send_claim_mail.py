#!/usr/bin/env python3
"""Preview, then send, a claim email through neomutt/mutt. Sending needs a
confirmation code that only the preview prints, so nothing goes out until a
person has seen exactly what will be sent and what is being claimed.

    python send_claim_mail.py preview job.json
    python send_claim_mail.py send job.json --confirm <code from preview>

job.json:
    {"to": ["accounts@example.org"], "cc": [],
     "subject": "Re: Reimbursement thread for <grant>",
     "in_reply_to": "<msg-id@host>",            (optional; reply in a thread)
     "references": "<root@host> <msg-id@host>",  (optional)
     "body": "path/to/body.txt",
     "attachments": ["Combined_Claim.pdf", "..."],
     "mutt": "neomutt", "muttrc": "~/.mutt/muttrc"}   (optional)

preview  builds the real MIME message but hands it to a capture script
         instead of a mail server: smtp_url is unset and sendmail points at a
         file writer. It checks that mutt accepted those settings before
         building anything, and that the captured file is non-empty afterwards.
         It prints headers, body, attachments, and a "what is being claimed"
         section read from each attached PDF's first page (the cover page that
         build_combined_claim.py writes).
send     refuses unless --confirm matches a hash of the job file, the body
         and every attachment's bytes, so any change after the preview needs a
         new preview. sendmail is set to /usr/bin/false, so a missing or
         rejected smtp_url fails instead of silently falling back to the
         local mail queue. On a terminal it also asks you to type SEND.

Needs pdftotext (poppler) for the claim summary.
"""

import argparse
import email
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from email import policy


def load(job_path):
    job = json.load(open(job_path))
    job["mutt"] = job.get("mutt", "neomutt")
    job["muttrc"] = os.path.expanduser(job.get("muttrc", "~/.mutt/muttrc"))
    missing = [
        p for p in [job["body"], *job.get("attachments", [])] if not os.path.isfile(p)
    ]
    if missing:
        sys.exit(f"ABORT: missing file(s): {missing}")
    return job


def code(job_path, job):
    h = hashlib.sha256(open(job_path, "rb").read())
    for p in [job["body"], *job.get("attachments", [])]:
        h.update(open(p, "rb").read())
    return h.hexdigest()[:8]


def mutt_args(job, settings):
    args = [job["mutt"], "-F", job["muttrc"]]
    for s in settings:
        args += ["-e", s]
    if job.get("in_reply_to"):
        args += ["-e", f"my_hdr In-Reply-To: {job['in_reply_to']}"]
        args += [
            "-e",
            f"my_hdr References: {job.get('references') or job['in_reply_to']}",
        ]
    args += ["-s", job["subject"]]
    for c in job.get("cc", []):
        args += ["-c", c]
    for a in job.get("attachments", []):
        args += ["-a", a]
    return args + ["--", *job["to"]]


def query(job, settings, names):
    out = subprocess.run(
        [
            job["mutt"],
            "-F",
            job["muttrc"],
            *sum([["-e", s] for s in settings], []),
            "-Q",
            *names,
        ],
        capture_output=True,
        text=True,
    ).stdout
    return dict(
        line.split(" = ", 1)
        for line in out.replace("set ", "").splitlines()
        if " = " in line
    )


def claim_summary(pdf):
    text = subprocess.run(
        ["pdftotext", "-layout", "-l", "1", pdf, "-"], capture_output=True, text=True
    ).stdout
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    return lines if any("total" in l.lower() for l in lines) else []


def preview(job_path, job):
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "message.eml")
    cap = os.path.join(tmp, "capture.sh")
    open(cap, "w").write(f"#!/bin/sh\ncat > {shlex.quote(out)}\n")
    os.chmod(cap, 0o700)
    settings = ["unset smtp_url", f"set sendmail={cap}", 'set record=""', "set copy=no"]
    got = query(job, settings, ["sendmail", "smtp_url"])
    if got.get("sendmail", "").strip('"') != cap or got.get("smtp_url") not in (
        '""',
        "",
    ):
        sys.exit(
            f"ABORT: mutt did not accept the capture settings, nothing built: {got}"
        )
    r = subprocess.run(
        mutt_args(job, settings),
        stdin=open(job["body"]),
        capture_output=True,
        text=True,
    )
    if r.returncode or not os.path.exists(out) or os.path.getsize(out) == 0:
        sys.exit(
            f"ABORT: preview not captured (exit {r.returncode}): {r.stderr.strip()}"
        )
    m = email.message_from_binary_file(open(out, "rb"), policy=policy.default)
    print("=" * 70)
    for h in ("From", "To", "Cc", "Subject", "In-Reply-To"):
        if m[h]:
            print(f"{h}: {m[h]}")
    print("-" * 70)
    print(m.get_body(("plain",)).get_content().strip())
    print("-" * 70)
    print("Attachments:")
    for p in m.iter_attachments():
        print(f"  - {p.get_filename()} ({len(p.get_content()) // 1024} KB)")
    for a in job.get("attachments", []):
        if a.lower().endswith(".pdf") and (s := claim_summary(a)):
            print("-" * 70)
            print(f"What is being claimed ({os.path.basename(a)}, cover page):")
            print("\n".join("  " + l for l in s))
    print("=" * 70)
    print(f"Nothing was sent. Rendered message: {out}")
    print(
        f"To send exactly this: {sys.argv[0]} send {job_path} --confirm {code(job_path, job)}"
    )


def send(job_path, job, confirm):
    if confirm != code(job_path, job):
        sys.exit(
            "ABORT: confirmation code doesn't match. The job, body or an attachment changed since the preview "
            "(or the code is wrong). Run preview again."
        )
    if (
        sys.stdin.isatty()
        and input(f"Send '{job['subject']}' to {', '.join(job['to'])}? Type SEND: ")
        != "SEND"
    ):
        sys.exit("Not sent.")
    settings = [
        "set sendmail=/usr/bin/false"
    ]  # never fall back to the local mail queue
    if query(job, settings, ["smtp_url"]).get("smtp_url") in (None, '""', ""):
        sys.exit("ABORT: smtp_url is not set in the muttrc; refusing to send.")
    r = subprocess.run(
        mutt_args(job, settings),
        stdin=open(job["body"]),
        capture_output=True,
        text=True,
    )
    if r.returncode:
        sys.exit(f"SEND FAILED (exit {r.returncode}): {r.stderr.strip()}")
    print(
        f"Sent: {job['subject']} -> {', '.join(job['to'])}. Check the copy in your Sent folder."
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["preview", "send"])
    ap.add_argument("job")
    ap.add_argument("--confirm")
    a = ap.parse_args()
    j = load(a.job)
    preview(a.job, j) if a.mode == "preview" else send(a.job, j, a.confirm)
