"""Booking flow end to end — the script the API calls.

    python -m app.services.flow

Runs a full demo against a scratch database: request -> quote -> proposal ->
e-signature -> deposit invoice -> payment -> confirmation emails -> balance.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import booking, emails, pricing, terms

BASE_URL = os.environ.get("BHC_BASE_URL", "http://localhost:8080")


def money_lines(lines: list[dict]) -> str:
    out = []
    for l in lines:
        if l.get("needsQuote"):
            out.append(f"• {l['name']} — quoted by VIN")
        else:
            out.append(f"• {l['name']} — ${l['unit']:.2f}")
    return "\n".join(out)


def run_demo(payload: dict, db_path: str = ":memory:") -> dict:
    dbmod.DB_PATH = db_path
    dbmod.init()
    cat = pricing.load_catalog()
    with dbmod.db() as conn:
        t = terms.install_templates(conn, cat)
        terms_doc = terms.active_terms(conn)

        out = booking.create_booking(conn, cat, payload)
        pid = out["proposal"]["proposalId"]
        conn.execute("UPDATE proposals SET terms_version=?, terms_hash=?, status='sent',"
                     " sent_at=datetime('now') WHERE id=?",
                     (terms_doc["version"], terms_doc["sha256"], pid))

        client = payload["client"]
        totals = out["quote"]["totals"]
        if not out["quote"]["slot"]:
            out["quote"]["slot"] = pricing.slot_for(cat, payload.get("items") or [],
                                                    datetime.now() + timedelta(days=2))
        start = datetime.fromisoformat(out["quote"]["slot"]["start"])
        ctx = {
            "first_name": client["name"].split()[0],
            "email": client["email"],
            "phone": cat["shop"]["phone"],
            "vehicle": payload["vehicle"].get("model", "BMW"),
            "number": out["proposal"]["number"],
            "summary": money_lines(out["quote"]["lines"]),
            "travel_line": (f"{out['quote']['travel']['miles']} mi each way — "
                            f"${out['quote']['travel']['travelFee']:.2f}") if out["quote"]["travel"] else "n/a",
            "link": f"{BASE_URL}/p/{out['proposal']['publicToken']}",
            "expires": out["proposal"]["expiresAt"][:10],
            "date": start.strftime("%A %b %d"),
            "time": start.strftime("%-I:%M %p") if os.name != "nt" else start.strftime("%I:%M %p").lstrip("0"),
            "address": f"{client['address']}, {client['city']} NJ",
            "balance": f"{totals['balance']:.2f}",
            "deposit": f"{totals['deposit']:.2f}",
            "scheduled_start": out["quote"]["slot"]["start"],
            "service": ", ".join(l["name"] for l in out["quote"]["lines"] if l["kind"] == "service"),
        }
        email_ids = emails.on_request(conn, out, ctx)

        sig = booking.sign_proposal(conn, pid, {
            "name": client["name"], "image": "data:image/png;base64,iVBORw0KGgo=",
            "ip": "73.11.22.33", "ua": "Mozilla/5.0 (iPhone)"})
        emails.cancel_pending(conn, out["bookingId"], ["proposal_reminder"])

        inv = booking.create_invoice(conn, out["bookingId"], pid, "deposit")
        emails.on_signed(conn, out["bookingId"], inv, {**ctx, "invoice_link": f"{BASE_URL}/i/{inv['publicToken']}"})

        pay = booking.record_payment(conn, inv["invoiceId"], totals["deposit"], "card", "stripe", "pi_demo")
        emails.on_deposit_paid(conn, out["bookingId"], ctx)

        balance_inv = booking.create_invoice(conn, out["bookingId"], pid, "balance")
        emails.queue(conn, client["email"], "invoice_sent",
                     {**ctx, "invoice": balance_inv["number"], "amount": f"{balance_inv['amountDue']:.2f}",
                      "link": f"{BASE_URL}/i/{balance_inv['publicToken']}"}, out["bookingId"])

        queued = dbmod.rows(conn.execute(
            "SELECT template, subject, status, scheduled_for FROM emails WHERE booking_id=? ORDER BY id",
            (out["bookingId"],)))
        state = dbmod.rows(conn.execute("SELECT code, status, scheduled_start FROM bookings"))
        invs = dbmod.rows(conn.execute("SELECT number, status, totals_json FROM invoices"))
        sig_row = dbmod.rows(conn.execute(
            "SELECT number, status, signature_name, signed_hash, terms_version FROM proposals"))
    return {"booking": state[0], "proposal": sig_row[0], "signature": sig,
            "invoices": [{**i, "totals": json.loads(i.pop("totals_json"))} for i in invs],
            "payment": pay, "emails": queued, "terms": t, "quoteTotals": totals}


if __name__ == "__main__":
    demo = {
        "client": {"name": "Sarah Johnson", "email": "sarah@example.com", "phone": "7325551234",
                   "address": "12 Ocean Ave", "city": "Point Pleasant", "zip": "08742",
                   "lat": 40.0832, "lng": -74.0682},
        "vehicle": {"vin": "WBA3A5C55CF256789", "model": "2012 BMW 335i"},
        "items": ["oil-service", "brake-pads-rotors"],
        "addons": ["add-cabin-filter"],
        "when": (datetime.now() + timedelta(days=3)).replace(hour=10, minute=0).isoformat(timespec="minutes"),
    }
    print(json.dumps(run_demo(demo), indent=2, default=str))
