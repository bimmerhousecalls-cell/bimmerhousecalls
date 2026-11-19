"""Automated emails: templates, the queue, and the trigger rules.

Emails are written to the `emails` table with a scheduled time and sent by the
worker (Gmail API here; swap `send_fn` for SMTP/Resend anywhere else). Nothing
is sent inline during a web request, so a slow mail API never blocks a booking.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import db as dbmod

SUBJECTS = {
    "proposal_sent": "Your Bimmer House Calls quote {number} — review & sign",
    "proposal_reminder": "Reminder: your quote {number} is waiting for a signature",
    "proposal_signed": "Signed — thanks! Deposit invoice {invoice} inside",
    "booking_confirmed": "You're booked for {date} — what to expect",
    "day_before": "Tomorrow: your mobile service at {time}",
    "on_my_way": "On my way — about {eta} minutes out",
    "invoice_sent": "Invoice {invoice} — ${amount} due",
    "payment_receipt": "Payment received — thank you",
    "balance_due": "Balance due on invoice {invoice}",
    "review_request": "How did the {service} go?",
    "annual_plan_offer": "Your annual maintenance plan is due",
    "quote_for_approval": "Quote {number} — approve and pick your date",
    "invoice_manual": "Invoice {invoice} from Bimmer House Calls — ${amount}",
    "deposit_request": "Deposit invoice {invoice} for your custom order — ${deposit}",
    "reschedule": "Your appointment moved to {date} at {time}",
    "cancellation": "Your appointment is cancelled — {code}",
    "follow_up_lead": "Still want a price on the {vehicle}?",
    "owner_new_lead": "New request: {client} — {vehicle} — ${total}",
    "owner_signed": "{client} signed — {code} is booked",
    "owner_paid": "Payment ${amount} — {invoice}",
}


BRAND_INK = "#0B0B0D"
BRAND_YELLOW = "#FFD400"


def _shell(body: str, shop: dict, footer_note: str = "") -> str:
    """One consistent look for every email: yellow rule, readable type, quiet footer."""
    safe_name = shop.get("name", "Bimmer House Calls")
    phone = shop.get("phone", "")
    email = shop.get("email", "")
    logo = (shop.get("logo") or {}).get("card") or (shop.get("logo") or {}).get("file") or ""
    base = os.environ.get("BHC_BASE_URL", "").rstrip("/")
    logo_html = (f'<img src="{base}{logo}" alt="{safe_name}" height="34" '
                 f'style="display:block;height:34px;width:auto;border:0">' if logo and base else
                 f'<b style="font-size:17px;letter-spacing:.3px">{safe_name}</b>')
    paras = "".join(
        f'<p style="margin:0 0 14px">{line}</p>' for line in body.strip().split("\n\n") if line.strip())
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f5f7">
<div style="background:#f4f5f7;padding:26px 14px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;border-collapse:collapse">
    <tr><td style="background:{BRAND_INK};border-radius:14px 14px 0 0;padding:18px 24px">
      {logo_html}
    </td></tr>
    <tr><td style="height:4px;background:{BRAND_YELLOW};font-size:0;line-height:0">&nbsp;</td></tr>
    <tr><td style="background:#ffffff;padding:26px 24px;border:1px solid #e5e8ec;border-top:0;
                   font-size:15px;line-height:1.62;color:{BRAND_INK}">
      {paras}
    </td></tr>
    <tr><td style="background:#ffffff;border:1px solid #e5e8ec;border-top:0;border-radius:0 0 14px 14px;
                   padding:16px 24px;font-size:12.5px;line-height:1.55;color:#5b6470">
      {footer_note}
      <div style="margin-top:6px"><b style="color:{BRAND_INK}">{safe_name}</b> · Mobile BMW service &amp; performance</div>
      <div>{phone} · {email}</div>
      <div style="margin-top:8px;color:#8a929c">You are getting this because you booked service with us.
      Reply to this email any time and a real person answers.</div>
    </td></tr>
  </table>
</div></body></html>"""


def render(template: str, ctx: dict) -> tuple[str, str]:
    subject = SUBJECTS.get(template, "Bimmer House Calls").format(**ctx)
    body = TEMPLATES.get(template, "").format(**ctx)
    shop = ctx.get("shop") or {}
    if not shop:
        try:
            from app.services import pricing
            shop = pricing.load_catalog()["shop"]
        except Exception:  # noqa: BLE001
            shop = {}
    # make links clickable and keep the plain-text version readable
    import re as _re
    html_body = _re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#0B0B0D;font-weight:600">\1</a>', body)
    html_body = html_body.replace("\n", "<br>")
    note = ""
    cta = ctx.get("cta_link") or ""
    if cta:
        note = (f'<div style="margin-bottom:10px"><a href="{cta}" '
                f'style="display:inline-block;background:{BRAND_YELLOW};color:{BRAND_INK};'
                f'text-decoration:none;font-weight:700;padding:11px 20px;border-radius:9px">'
                f'{ctx.get("cta_label", "Open your invoice")}</a></div>')
    return subject, _shell(html_body, shop, note)


BASE = """Bimmer House Calls · Mobile BMW service & performance
{phone} · {email}
"""

TEMPLATES = {
    "proposal_sent": """Hi {first_name},

Thanks for the request on your {vehicle}. Here is your quote {number}:

{summary}

Travel: {travel_line}

Review, sign, and pay the deposit here:
{link}

The quote is good through {expires}. Reply to this email or call {phone} with any questions.

— Bimmer House Calls
""",
    "proposal_reminder": """Hi {first_name},

Just a nudge — your quote {number} for the {vehicle} hasn't been signed yet, and it expires {expires}.

Sign and lock in your date: {link}

— Bimmer House Calls
""",
    "proposal_signed": """Hi {first_name},

Signed and on file — thank you. Your deposit invoice {invoice} for ${deposit} is here:
{link}

Once the deposit is in, your date is locked and any parts get ordered.

— Bimmer House Calls
""",
    "booking_confirmed": """Hi {first_name},

You're booked: {date} at {time}, at {address}.

Job: {summary}
Balance due at completion: ${balance}

I'll text before I head over. If the address or the car changes, reply here so the travel
fee and the schedule stay right.

— Bimmer House Calls
""",
    "day_before": """Hi {first_name},

Reminder — tomorrow at {time} at {address} for the {vehicle}.

Please leave about a car-length of clear space and have the car unlocked. If anything
changed, reply now.

— Bimmer House Calls
""",
    "on_my_way": """Hi {first_name},

Heading your way — about {eta} minutes out.

— Bimmer House Calls
""",
    "invoice_sent": """Hi {first_name},

Here is invoice {invoice} for ${amount}, for the work on your {vehicle}:

{link}

Open it any time — it shows every line, the labor price, the terms you signed and your signature. Pay by cash or check when the work is done. Nothing is charged online.

— Bimmer House Calls
""",
    "payment_receipt": """Hi {first_name},

Payment received — ${amount} on invoice {invoice}. Remaining balance: ${balance}.

Thank you,
— Bimmer House Calls
""",
    "balance_due": """Hi {first_name},

A friendly reminder that invoice {invoice} has a balance of ${balance}:
{link}

— Bimmer House Calls
""",
    "review_request": """Hi {first_name},

Thanks for having me out for the {service}. If it went well, a quick Google review goes a
long way for a one-man shop — it's the only advertising I have.

Anything not right, reply here first and I'll make it right.

— Bimmer House Calls
""",
    "quote_for_approval": """Hi {first_name},

Here is your quote {number} for the {vehicle}:

{summary}

Travel: {travel_line}
Total: ${total}

Approve it and pick a date here: {link}

Prices hold for 14 days. Questions? Reply here or call {phone}.

— Bimmer House Calls
""",
    "invoice_manual": """Hi {first_name},

Invoice {invoice} — ${amount} due.

{summary}

Pay here: {link}
Cash or check on site. Nothing is charged online.

— Bimmer House Calls
""",
    "deposit_request": """Hi {first_name},

Thanks for the custom build request on the {vehicle}. Quote {number} is ${total}, and the
deposit to get parts ordered is ${deposit} ({deposit_pct}%).

Sign and pay the deposit here: {link}

Once the deposit clears, parts get ordered and we lock the date.

— Bimmer House Calls
""",
    "reschedule": """Hi {first_name},

Your appointment for the {vehicle} moved to {date} at {time}. Everything else stays the same.
If that doesn't work, reply with a better day.

— Bimmer House Calls
""",
    "cancellation": """Hi {first_name},

Appointment {code} is cancelled. No hard feelings — reply whenever you want to book again.

— Bimmer House Calls
""",
    "follow_up_lead": """Hi {first_name},

You priced the {vehicle} a while back and didn't lock a date. Still interested? Reply with a
day and I'll send an updated quote — prices on parts move.

— Bimmer House Calls
""",
    "owner_new_lead": """New request from the website.

{client} · {phone} · {email}
{vehicle} · VIN {vin}
{address}
{date} {time}

{summary}
Travel: {travel_line}
Total: ${total}

Open it in the dashboard: {admin_link}
""",
    "owner_signed": """{client} signed the terms and the job is on the calendar.

{code} · {date} {time}
{vehicle} · {address}

Open it: {admin_link}
""",
    "owner_paid": """Payment recorded: ${amount} on invoice {invoice} ({method}).

Balance left on the job: ${balance}
""",
    "annual_plan_offer": """Hi {first_name},

Your annual maintenance plan on the {vehicle} is due for its next visit. Want me to put the
same slots on the calendar again? Reply "yes" and I'll send the plan.

— Bimmer House Calls
""",
}


def queue(conn, to_email: str, template: str, ctx: dict, booking_id: int | None = None,
          when: datetime | None = None) -> int:
    # invoice emails: attach a PDF copy so the client has it without opening a link
    ctx = {**ctx}
    if template in ("invoice_sent", "invoice_manual", "deposit_request") and not ctx.get("attach"):
        try:
            tok = (ctx.get("link") or "").rsplit("/", 1)[-1]
            if tok:
                from app.services import invoice_pdf
                ctx["attach"] = invoice_pdf.render(tok)
        except Exception:  # noqa: BLE001 - a missing attachment must not stop the email
            pass
    subject, body = render(template, ctx)
    cur = conn.execute(
        "INSERT INTO emails(to_email, subject, body, template, booking_id, status, scheduled_for, attachment)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (to_email, subject, body, template, booking_id, "queued",
         (when or datetime.now()).isoformat(timespec="minutes"), ctx.get("attach") or ""))
    eid = cur.lastrowid
    # free hosts have no cron: send it a few seconds from now, after this commits
    if when is None:
        try:
            from app.services import mailer
            mailer.schedule_flush()
        except Exception:  # noqa: BLE001
            pass
    return eid


# ------------------------------------------------------------------ triggers

def on_request(conn, booking: dict, ctx: dict) -> list[int]:
    """A new website request came in: send the proposal now, remind at +48h."""
    ids = [queue(conn, ctx["email"], "proposal_sent", ctx, booking["bookingId"])]
    ids.append(queue(conn, ctx["email"], "proposal_reminder", ctx, booking["bookingId"],
                     when=datetime.now() + timedelta(hours=48)))
    return ids


def on_signed(conn, booking_id: int, invoice: dict, ctx: dict) -> list[int]:
    return [queue(conn, ctx["email"], "proposal_signed",
                  {**ctx, "invoice": invoice["number"], "deposit": f"{invoice['amountDue']:.2f}",
                   "link": ctx.get("invoice_link", "")}, booking_id)]


def on_deposit_paid(conn, booking_id: int, ctx: dict) -> list[int]:
    """Confirmation now, day-before reminder, receipt, and a review ask after the job."""
    start = datetime.fromisoformat(ctx["scheduled_start"])
    ids = [queue(conn, ctx["email"], "booking_confirmed", ctx, booking_id)]
    ids.append(queue(conn, ctx["email"], "day_before", ctx, booking_id,
                     when=(start - timedelta(days=1)).replace(hour=17, minute=0)))
    ids.append(queue(conn, ctx["email"], "review_request", ctx, booking_id,
                     when=start + timedelta(days=1, hours=20)))
    return ids


def due(conn, limit: int = 50) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM emails WHERE status='queued' AND (scheduled_for IS NULL OR scheduled_for<=?)"
        " ORDER BY id LIMIT ?", (datetime.now().isoformat(timespec="minutes"), limit))
    return [dict(r) for r in cur.fetchall()]


def mark(conn, email_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE emails SET status=?, error=?, sent_at=CASE WHEN ?='sent' THEN datetime('now')"
                 " ELSE sent_at END WHERE id=?", (status, error, status, email_id))


def cancel_pending(conn, booking_id: int, templates: list[str] | None = None) -> int:
    """Un-sent reminders for a booking (e.g. once it's signed, drop the nudge)."""
    q = "UPDATE emails SET status='skipped' WHERE booking_id=? AND status='queued'"
    params: list = [booking_id]
    if templates:
        q += " AND template IN (%s)" % ",".join("?" * len(templates))
        params += templates
    return conn.execute(q, params).rowcount


if __name__ == "__main__":
    print(json.dumps(render("proposal_sent", {
        "first_name": "Sarah", "vehicle": "2012 BMW 335i", "number": "P-2026-1001",
        "summary": "• Oil service — $200", "travel_line": "36 mi each way — $55",
        "link": "https://book.bimmerhousecalls.com/p/abc", "expires": "Feb 20",
        "phone": "(732) 890-8458", "email": "bimmerhousecalls@gmail.com"}), indent=2))
