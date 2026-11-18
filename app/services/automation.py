"""The scheduler: what a cron/worker run does every few minutes.

    python -m app.services.automation          # run everything once
    python -m app.services.automation --dry-run

Jobs, all idempotent (safe to run as often as you like):
  * send every queued email that is due
  * 48h reminder for quotes still unsigned
  * 14-day follow-up on dead leads
  * balance invoice + email the day after a completed job (standard orders)
  * day-before and review-ask emails if one was ever missed
  * mark quotes expired after their window
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import booking, emails, worker

BASE_URL = os.environ.get("BHC_BASE_URL", "http://localhost:8080")


def _ctx(conn, b, c, v, totals, lines) -> dict:
    start = datetime.fromisoformat(b["scheduled_start"]) if b["scheduled_start"] else None
    return {
        "first_name": (c["name"] or "there").split()[0], "email": c["email"], "phone": "(732) 890-8458",
        "vehicle": (v["model"] if v and v["model"] else "BMW"), "number": b["code"],
        "summary": "\n".join(f"• {l['name']} — ${l['unit']:.2f}" if l.get("unit") else f"• {l['name']}"
                             for l in lines),
        "travel_line": f"{b['travel_miles']} mi each way — ${b['travel_fee']:.2f}",
        "link": "", "expires": "", "total": f"{totals.get('total', 0):.2f}",
        "date": start.strftime("%a %b %d") if start else "", "time": start.strftime("%I:%M %p").lstrip("0") if start else "",
        "address": f"{c['address'] or ''}, {c['city'] or ''} {c['state'] or 'NJ'}",
        "balance": f"{totals.get('balance', 0):.2f}", "deposit": f"{totals.get('deposit', 0):.2f}",
        "deposit_pct": totals.get("depositPercent", 25),
        "scheduled_start": b["scheduled_start"] or "",
        "service": ", ".join(l["name"] for l in lines if l.get("kind") == "service"),
    }


def run(dry_run: bool = False) -> dict:
    out = {"reminders": 0, "followUps": 0, "balanceInvoices": 0, "expired": 0, "emails": {}}
    now = datetime.now()
    with dbmod.db() as conn:
        rows = dbmod.rows(conn.execute(
            "SELECT b.*, c.email, c.name cname, c.address, c.city, c.state, v.model FROM bookings b"
            " JOIN clients c ON c.id=b.client_id LEFT JOIN vehicles v ON v.id=b.vehicle_id"))

        for b in rows:
            props = dbmod.rows(conn.execute("SELECT * FROM proposals WHERE booking_id=? ORDER BY id DESC",
                                            (b["id"],)))
            if not props:
                continue
            p = props[0]
            totals = json.loads(p["totals_json"] or "{}")
            lines = json.loads(p["lines_json"] or "[]")
            c = {"email": b["email"], "name": b["cname"], "address": b["address"], "city": b["city"], "state": b["state"]}
            ctx = _ctx(conn, b, c, b, totals, lines)

            # quote expiring
            if p["status"] in ("sent", "viewed") and p["expires_at"] and p["expires_at"] < now.isoformat(timespec="minutes"):
                if not dry_run:
                    conn.execute("UPDATE proposals SET status='expired' WHERE id=?", (p["id"],))
                out["expired"] += 1

            # follow-up on dead leads (14 days, once)
            if p["status"] in ("sent", "viewed", "expired") and p["created_at"]:
                created = datetime.fromisoformat(p["created_at"])
                already = conn.execute("SELECT 1 FROM emails WHERE booking_id=? AND template='follow_up_lead'",
                                       (b["id"],)).fetchone()
                if created < now - timedelta(days=14) and not already and not dry_run:
                    emails.queue(conn, c["email"], "follow_up_lead",
                                 {**ctx, "vehicle": (b["model"] or "BMW")}, b["id"])
                    out["followUps"] += 1

            # job finished -> balance invoice for standard orders (no deposit taken)
            if b["status"] in ("confirmed", "in_progress", "done") and b["scheduled_end"]:
                ended = datetime.fromisoformat(b["scheduled_end"])
                has_balance = conn.execute(
                    "SELECT 1 FROM invoices WHERE booking_id=? AND totals_json LIKE '%\"kind\": \"balance\"%'",
                    (b["id"],)).fetchone()
                if ended < now and not has_balance and totals.get("total") and not dry_run:
                    inv = booking.create_invoice(conn, b["id"], p["id"], "balance")
                    emails.queue(conn, c["email"], "invoice_sent",
                                 {**ctx, "invoice": inv["number"], "amount": f"{inv['amountDue']:.2f}",
                                  "link": f"{BASE_URL}/i/{inv['publicToken']}"}, b["id"])
                    conn.execute("UPDATE bookings SET status='done' WHERE id=?", (b["id"],))
                    out["balanceInvoices"] += 1

        # anything due to send right now
        if not dry_run:
            out["emails"] = worker.drain()
        else:
            out["emails"] = {"dryRun": True, "due": len(emails.due(conn))}
    return out


if __name__ == "__main__":
    print(json.dumps(run(dry_run="--dry-run" in sys.argv), indent=2))
