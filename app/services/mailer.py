"""Send the queued mail through the Gmail connector.

The queue in SQLite stays the source of truth: every email is written down
first, then this pushes it out. If a send fails it stays 'queued' and is retried
on the next pass — nothing is lost.

    python -m app.services.mailer --dry-run     # show what would go out
    python -m app.services.mailer               # send what's due
    python -m app.services.mailer --digest      # owner digest only
    python -m app.services.mailer --outbox      # write each due email as .html for the Gmail tool

`--outbox` is what the bot uses: Gmail is connected to the bot, not to a Python
process, so each queued email is written to data/outbox/<id>.html and the bot
sends it with the Gmail tool, then runs `--mark <id> sent`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import emails, pricing


def _connector_send(to: str, subject: str, body: str) -> bool:
    """Hand off to the Gmail connector when running inside the bot.

    In a standalone process there is no connector, so this returns False and the
    queue keeps the row for the bot's next pass (or the SMTP fallback below).
    """
    try:
        from app.services.gmail_bridge import send as bridge_send  # optional adapter
    except Exception:
        return False
    return bridge_send(to, subject, body)


def _smtp_send(to: str, subject: str, body: str) -> bool:
    """Optional direct SMTP. Needs BHC_SMTP_USER + BHC_SMTP_PASS (app password)."""
    user, pwd = os.environ.get("BHC_SMTP_USER"), os.environ.get("BHC_SMTP_PASS")
    if not (user and pwd):
        return False
    import smtplib
    from email.message import EmailMessage
    cat = pricing.load_catalog()
    msg = EmailMessage()
    msg["From"] = f"{cat['shop'].get('name', 'Bimmer House Calls')} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    # a plain-text part, then the branded HTML version
    msg.set_content(re.sub(r"<[^>]+>", "", body))
    msg.add_alternative(body if "<" in body else f"<pre>{body}</pre>", subtype="html")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True


def send_now(to: str, subject: str, body: str) -> str:
    """Try the connector, then SMTP; report which path worked."""
    if _connector_send(to, subject, body):
        return "gmail-connector"
    if _smtp_send(to, subject, body):
        return "smtp"
    return "queued"


def diagnose() -> dict:
    """Why did nothing send? Report each path honestly."""
    user = os.environ.get("BHC_SMTP_USER")
    pwd = os.environ.get("BHC_SMTP_PASS")
    out = {"smtpUser": bool(user), "smtpPass": bool(pwd), "connector": False,
           "sender": "none", "problem": ""}
    try:
        from app.services.gmail_bridge import send as _b  # noqa: F401
        out["connector"] = True
    except Exception:
        pass
    if user and pwd:
        try:
            import smtplib
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
                s.starttls()
                s.login(user, pwd)
            out["sender"] = "smtp"
        except Exception as exc:  # noqa: BLE001
            out["problem"] = f"SMTP login failed: {exc}"
    elif out["connector"]:
        out["sender"] = "connector"
    else:
        out["problem"] = ("No sender configured. Set BHC_SMTP_USER and BHC_SMTP_PASS "
                          "(a Gmail app password) on the server.")
    return out


def drain(limit: int = 50, dry_run: bool = False) -> dict:
    sent = failed = 0
    log = []
    with dbmod.db() as conn:
        for row in emails.due(conn, limit):
            if dry_run:
                log.append({"to": row["to_email"], "subject": row["subject"]})
                continue
            try:
                how = send_now(row["to_email"], row["subject"], row["body"])
                if how == "queued":
                    log.append({"to": row["to_email"], "subject": row["subject"], "status": "no-sender"})
                    failed += 1
                    continue
                emails.mark(conn, row["id"], "sent", how)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                emails.mark(conn, row["id"], "failed", str(exc)[:400])
                failed += 1
    return {"sent": sent, "failed": failed, "dryRun": dry_run, "log": log}


def digest() -> dict:
    """One morning email: today's jobs, new requests, money owed, things waiting."""
    cat = pricing.load_catalog()
    today = datetime.now().date().isoformat()
    with dbmod.db() as conn:
        rows = dbmod.rows(conn.execute(
            "SELECT b.*, c.name AS client, c.phone, v.model FROM bookings b"
            " JOIN clients c ON c.id=b.client_id LEFT JOIN vehicles v ON v.id=b.vehicle_id"
            " WHERE date(b.scheduled_start)=? AND b.status NOT IN ('cancelled')"
            " ORDER BY b.scheduled_start", (today,)))
        new = dbmod.rows(conn.execute(
            "SELECT COUNT(*) n FROM bookings WHERE status IN ('lead','quoted','sent')"))
        owed = 0.0
        for inv in dbmod.rows(conn.execute("SELECT totals_json FROM invoices WHERE status IN ('open','partial')")):
            t = json.loads(inv["totals_json"] or "{}")
            owed += float(t.get("amountDue", 0)) - float(t.get("paid", 0))
        waiting = dbmod.rows(conn.execute(
            "SELECT COUNT(*) n FROM proposals WHERE status='sent'"))
    lines = [f"Good morning. {len(rows)} job(s) today, {new[0]['n'] if new else 0} request(s) waiting,",
             f"${owed:.2f} owed on open invoices, {waiting[0]['n'] if waiting else 0} quote(s) unsigned.", ""]
    for r in rows:
        lines.append(f"  {(r['scheduled_start'] or '')[11:16]}  {r['client']} · {r['model'] or ''} · {r['status']}")
    if not rows:
        lines.append("  Nothing booked today.")
    body = "\n".join(lines)
    to = cat["shop"]["email"]
    how = send_now(to, f"Bimmer House Calls — today, {datetime.now().strftime('%a %b %d')}", body)
    return {"to": to, "how": how, "body": body}


OUTBOX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "data", "outbox")


def write_one(row: dict) -> str:
    """Write one queued email as a standalone HTML file for the Gmail tool."""
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    path = os.path.join(OUTBOX_DIR, f"{row['id']}.html")
    html = ("<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;"
            "line-height:1.55;color:#0B0B0D;max-width:620px\">"
            + "<div style=\"border-left:4px solid #FFD400;padding-left:14px\">"
            + row["body"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
            + "</div><p style=\"color:#5b6470;font-size:12px;margin-top:18px\">Bimmer House Calls · "
              "mobile BMW service · Jersey Shore</p></div>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def write_outbox(limit: int = 25) -> list[dict]:
    """Turn due emails into files the Gmail tool can send verbatim."""
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "data", "outbox")
    os.makedirs(out_dir, exist_ok=True)
    out = []
    with dbmod.db() as conn:
        for row in emails.due(conn, limit):
            path = os.path.join(out_dir, f"{row['id']}.html")
            html = ("<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;"
                    "line-height:1.55;color:#0B0B0D;max-width:620px\">"
                    + "<div style=\"border-left:4px solid #FFD400;padding-left:14px\">"
                    + row["body"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
                    + "</div><p style=\"color:#5b6470;font-size:12px;margin-top:18px\">Bimmer House Calls · "
                      "mobile BMW service · Jersey Shore</p></div>")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            out.append({"id": row["id"], "to": row["to_email"], "subject": row["subject"], "file": path})
    return out


def mark_sent(email_id: int, how: str = "gmail-connector") -> None:
    with dbmod.db() as conn:
        emails.mark(conn, email_id, "sent", how)


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        print(json.dumps(diagnose(), indent=2))
        raise SystemExit(0)
    if "--ids" in sys.argv:
        ids = [int(x) for x in sys.argv[sys.argv.index("--ids") + 1].split(",") if x.strip()]
        with dbmod.db() as conn:
            for i in ids:
                row = conn.execute("SELECT * FROM emails WHERE id=?", (i,)).fetchone()
                if row:
                    path = write_one(dict(row))
                    print(json.dumps({"id": i, "to": row["to_email"], "subject": row["subject"],
                                      "file": path}))
        raise SystemExit(0)
    if "--outbox" in sys.argv:
        print(json.dumps(write_outbox(), indent=2))
    elif "--mark" in sys.argv:
        mark_sent(int(sys.argv[sys.argv.index("--mark") + 1]))
        print("marked sent")
    elif "--digest" in sys.argv:
        print(json.dumps(digest(), indent=2))
    else:
        print(json.dumps(drain(dry_run="--dry-run" in sys.argv), indent=2))
