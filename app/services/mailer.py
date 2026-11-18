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
import threading
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
    """Send through Gmail over HTTPS (port 443), which no host blocks.

    Render's free tier has no outbound SMTP, so ports 587/465 fail with
    "Network is unreachable". Gmail's REST API goes over normal HTTPS instead.
    Needs BHC_SMTP_USER (the Gmail address) and BHC_SMTP_PASS (a 16-character
    Gmail app password).
    """
    user, pwd = os.environ.get("BHC_SMTP_USER"), os.environ.get("BHC_SMTP_PASS")
    if not (user and pwd):
        return False
    user, pwd = user.strip(), pwd.replace(" ", "").strip()
    import base64
    import json as jsonlib
    import urllib.error
    from email.message import EmailMessage
    import urllib.parse
    import urllib.request

    cat = pricing.load_catalog()
    shop_name = cat["shop"].get("name", "Bimmer House Calls")
    plain = re.sub(r"<[^>]+>", "", body)
    html = body if "<" in body else f"<pre>{body}</pre>"
    msg = EmailMessage()
    msg["From"] = f"{shop_name} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # OAuth refresh token first (the reliable path), then the app password
    refresh = os.environ.get("BHC_GOOGLE_REFRESH_TOKEN")
    if refresh:
        data = urllib.parse.urlencode({"client_id": os.environ.get("BHC_GOOGLE_CLIENT_ID", ""),
                                       "client_secret": os.environ.get("BHC_GOOGLE_CLIENT_SECRET", ""),
                                       "refresh_token": refresh,
                                       "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                access = jsonlib.loads(r.read())["access_token"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")[:200]
            if "invalid_grant" in detail:
                raise RuntimeError(
                    "Gmail refresh token is expired or revoked. Re-run the Google auth step "
                    "and put the new BHC_GOOGLE_REFRESH_TOKEN in the environment.") from None
            raise RuntimeError(f"Google token request failed: {detail}") from None
        req = urllib.request.Request(
            f"https://gmail.googleapis.com/gmail/v1/users/{urllib.parse.quote(user)}/messages/send",
            data=jsonlib.dumps({"raw": raw}).encode(),
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status == 200

    # Last resort: plain SMTP for hosts that do allow it
    import smtplib
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s2:
            s2.starttls()
            s2.login(user, pwd)
            s2.send_message(msg)
        return True
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError):
        import ssl
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20,
                              context=ssl.create_default_context()) as s2:
            s2.login(user, pwd)
            s2.send_message(msg)
        return True


def send_now(to: str, subject: str, body: str) -> str:
    """Try the connector, then SMTP; report which path worked."""
    if _connector_send(to, subject, body):
        return "gmail-connector"
    if _smtp_send(to, subject, body):
        return "smtp"
    return "queued"


def exchange_code(code: str) -> dict:
    """Trade Google's one-time code for a refresh token (used by /oauth/callback)."""
    import json as jsonlib
    import urllib.parse
    import urllib.request
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": os.environ.get("BHC_GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("BHC_GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("BHC_OAUTH_REDIRECT", ""),
        "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return jsonlib.loads(r.read())


def diagnose() -> dict:
    """Why did nothing send? Report each path honestly."""
    user = os.environ.get("BHC_SMTP_USER")
    pwd = os.environ.get("BHC_SMTP_PASS")
    refresh = os.environ.get("BHC_GOOGLE_REFRESH_TOKEN")
    out = {"smtpUser": bool(user), "smtpPass": bool(pwd), "connector": False,
           "gmailApi": bool(refresh), "sender": "none", "problem": "",
           "userSeen": (user or "")[:3] + "…" if user else "(empty)",
           "passLength": len((pwd or "").replace(" ", "")),
           "passHasSpaces": bool(pwd and " " in pwd),
           "passLooksLikeNormalPassword": bool(pwd and len(pwd.replace(" ", "")) != 16)}
    try:
        from app.services.gmail_bridge import send as _b  # noqa: F401
        out["connector"] = True
    except Exception:
        pass
    if refresh:
        out["sender"] = "gmail-api"
        return out
    if out["connector"]:
        out["sender"] = "connector"
        return out
    if user and pwd:
        # Can this host reach Gmail at all? Render's free tier cannot use SMTP.
        import socket
        reachable = False
        try:
            socket.create_connection(("smtp.gmail.com", 587), timeout=8).close()
            reachable = True
        except Exception:  # noqa: BLE001
            pass
        if not reachable:
            out["problem"] = ("This host blocks outbound SMTP (ports 587/465), so a Gmail app "
                              "password cannot send from here. Use a Gmail refresh token "
                              "(BHC_GOOGLE_REFRESH_TOKEN) or a paid instance.")
        else:
            try:
                import smtplib
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s2:
                    s2.starttls()
                    s2.login(user.strip(), pwd.replace(" ", "").strip())
                out["sender"] = "smtp"
            except Exception as exc:  # noqa: BLE001
                out["problem"] = f"SMTP login failed: {exc}"
    else:
        out["problem"] = ("No sender configured. Set BHC_SMTP_USER and BHC_SMTP_PASS "
                          "(a Gmail app password) on the server.")
    return out


_pending_flush = threading.Timer(0, lambda: None)


def schedule_flush(delay: float = 8.0) -> None:
    """Send what is queued a few seconds from now, without blocking the request.

    Free hosts have no cron, so the app flushes its own outbox. Safe to call on
    every queue write: only the newest timer is kept.
    """
    global _pending_flush
    try:
        _pending_flush.cancel()
    except Exception:  # noqa: BLE001
        pass
    _pending_flush = threading.Timer(delay, _flush_now)
    _pending_flush.daemon = True
    _pending_flush.start()


def _flush_now() -> None:
    try:
        drain()
    except Exception as exc:  # noqa: BLE001
        try:
            with open(os.path.join(os.path.dirname(dbmod.DB_PATH), "flush.log"), "a",
                      encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')} flush failed: {exc}\n")
        except Exception:  # noqa: BLE001
            pass


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
