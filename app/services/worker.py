"""Email worker — drains the queue.

Local mode (default): prints each email and marks it sent, so nothing is ever
silently lost while Gmail isn't wired up.
Gmail mode: set BHC_GMAIL_CMD to a command that reads {"to","subject","body"} as
JSON on stdin and sends it (the Gmail API send call), e.g.

    BHC_GMAIL_CMD="python gmail_send.py"

Run it on a schedule:  python -m app.services.worker   (cron every 5 min, or the
Routines tab). Idempotent: only rows still 'queued' are sent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import emails


def local_send(msg: dict) -> None:
    print(f"--- to: {msg['to']}\n    subject: {msg['subject']}\n{msg['body']}\n")


def gmail_send(msg: dict) -> None:
    cmd = os.environ["BHC_GMAIL_CMD"]
    proc = subprocess.run(cmd, shell=True, input=json.dumps(msg).encode(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode()[:500] or "gmail send failed")


def drain(limit: int = 50, dry_run: bool = False) -> dict:
    sender = gmail_send if os.environ.get("BHC_GMAIL_CMD") else local_send
    sent, failed = 0, 0
    with dbmod.db() as conn:
        for row in emails.due(conn, limit):
            msg = {"to": row["to_email"], "subject": row["subject"], "body": row["body"]}
            if dry_run:
                local_send(msg)
                continue
            try:
                sender(msg)
                emails.mark(conn, row["id"], "sent")
                sent += 1
            except Exception as exc:  # noqa: BLE001
                emails.mark(conn, row["id"], "failed", str(exc)[:500])
                failed += 1
    return {"sent": sent, "failed": failed, "dryRun": dry_run}


if __name__ == "__main__":
    print(json.dumps(drain(dry_run="--dry-run" in sys.argv), indent=2))
