"""The HTTP API — stdlib only (http.server), so it runs anywhere Python does.

    python -m app.api.server           # http://localhost:8080
    BHC_BASE_URL=https://api.example.com python -m app.api.server

Routes
  POST /api/quote              price a job + travel fee (no record created)
  POST /api/request            create lead + proposal, queue emails
  GET  /api/catalog            services, addons, packages, travel settings
  GET  /api/availability?date= YYYY-MM-DD open slots
  GET  /api/p/{token}          proposal for the client portal (JSON)
  POST /api/p/{token}/sign     e-signature  {name, image, consent}
  POST /api/p/{token}/decline
  GET  /api/i/{token}          invoice for the client portal (JSON)
  POST /api/admin/...          owner actions (see handle_admin)
  GET  /api/health
Static demo pages are served from app/static (/, /p/<token>, /i/<token>).
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import booking, emails, pricing, terms

BASE_URL = os.environ.get("BHC_BASE_URL", "http://localhost:8080").rstrip("/")
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
CORS_ORIGINS = os.environ.get(
    "BHC_CORS", "https://bimmerhousecalls.netlify.app,http://localhost:8080,http://127.0.0.1:8080"
).split(",")

_catalog_cache: dict = {}


def catalog() -> dict:
    if "c" not in _catalog_cache:
        _catalog_cache["c"] = pricing.load_catalog()
    return _catalog_cache["c"]


def money_lines(lines):
    return "\n".join(
        f"• {l['name']} — quoted by VIN" if l.get("needsQuote") else f"• {l['name']} — ${l['unit']:.2f}"
        for l in lines)


def email_ctx(conn, payload, out, client, start: datetime | None) -> dict:
    cat = catalog()
    t = out["quote"]["travel"]
    return {
        "first_name": (client.get("name") or "there").split()[0],
        "email": client["email"],
        "phone": cat["shop"]["phone"],
        "vehicle": (payload.get("vehicle") or {}).get("model") or "BMW",
        "number": out["proposal"]["number"],
        "summary": money_lines(out["quote"]["lines"]),
        "travel_line": f"{t['miles']} mi each way — ${t['travelFee']:.2f}" if t else "n/a",
        "link": f"{BASE_URL}/p/{out['proposal']['publicToken']}",
        "expires": out["proposal"]["expiresAt"][:10],
        "date": start.strftime("%a %b %d") if start else "",
        "time": start.strftime("%I:%M %p").lstrip("0") if start else "",
        "address": f"{client.get('address','')}, {client.get('city','')} {client.get('state','NJ')}",
        "balance": f"{out['quote']['totals']['balance']:.2f}",
        "deposit": f"{out['quote']['totals']['deposit']:.2f}",
        "scheduled_start": start.isoformat(timespec="minutes") if start else "",
        "service": ", ".join(l["name"] for l in out["quote"]["lines"] if l["kind"] == "service"),
    }


def notify_owner(conn, template: str, ctx: dict, booking_id: int | None = None) -> None:
    """Every new request / signature / payment also lands in the owner's inbox."""
    shop = catalog()["shop"]
    owner = (shop.get("alerts") or {}).get("to") or shop["email"]
    # the owner can switch any of these off in Settings
    gate = {"owner_new_lead": "onRequest", "owner_signed": "onSignature",
            "owner_paid": "onPayment", "owner_cancelled": "onCancel"}.get(template)
    if gate and not (shop.get("alerts") or {}).get(gate, True):
        return
    try:
        emails.queue(conn, owner, template, {**ctx, "admin_link": f"{BASE_URL}/admin"}, booking_id)
    except Exception:  # never let a notification break the client's flow
        pass


# ------------------------------------------------------------------ client endpoints

def do_quote(body: dict) -> dict:
    cat = catalog()
    when = None
    if body.get("when"):
        try:
            when = datetime.fromisoformat(str(body["when"]).strip())
        except ValueError:
            raise ValueError("Please pick a date and time from the list")
    q = booking.build_quote(cat, body, when)
    return {"quote": q, "catalog": {"shop": cat["shop"]}}


def do_request(body: dict) -> dict:
    cat = catalog()
    if not (body.get("client") or {}).get("email"):
        raise ValueError("email is required")
    if len(((body.get("vehicle") or {}).get("vin") or "").strip()) != 17:
        raise ValueError("A 17-character VIN is required for every quote")
    sig = body.get("signature") or {}
    if not (body.get("acknowledged") and body.get("consent")):
        raise ValueError("You must agree to the Terms and Conditions before sending the request")
    if not (sig.get("name") and sig.get("image")):
        raise ValueError("A signature is required before sending the request")
    with dbmod.db() as conn:
        terms.install_templates(conn, cat)
        tdoc = terms.active_terms(conn)
        # never double-book: the requested time must still be free for this job's length
        if body.get("when"):
            try:
                start = datetime.fromisoformat(str(body["when"]).strip())
            except ValueError:
                start = None
            if start:
                hrs = max(booking.build_quote(cat, body, start)["jobHours"], 0.5)
                end = start + timedelta(hours=hrs) + timedelta(minutes=30)
                clash = conn.execute(
                    "SELECT code FROM bookings WHERE scheduled_start < ? AND scheduled_end > ?"
                    " AND status NOT IN ('cancelled') LIMIT 1",
                    (end.isoformat(timespec="minutes"), start.isoformat(timespec="minutes"))).fetchone()
                if clash:
                    raise ValueError("That time was just taken — please pick another slot")
        out = booking.create_booking(conn, cat, body)
        conn.execute("UPDATE proposals SET terms_version=?, terms_hash=?, status='sent',"
                     " sent_at=datetime('now') WHERE id=?",
                     (tdoc["version"], tdoc["sha256"], out["proposal"]["proposalId"]))
        start = datetime.fromisoformat(out["quote"]["slot"]["start"]) if out["quote"]["slot"] else None
        ctx = email_ctx(conn, body, out, body["client"], start)
        sent = emails.on_request(conn, out, ctx)
        notify_owner(conn, "owner_new_lead", {
            **ctx, "client": body["client"].get("name", ""), "vin": (body.get("vehicle") or {}).get("vin", ""),
            "phone": body["client"].get("phone", ""), "email": body["client"].get("email", ""),
            "total": f"{out['quote']['totals']['total']:.2f}"}, out["bookingId"])
        # signed at the moment of request: book it, and only then invoice a deposit if it's custom
        ip = "0.0.0.0"
        signed = booking.sign_proposal(conn, out["proposal"]["proposalId"],
                                       {"name": sig["name"], "image": sig.get("image"), "ip": ip, "ua": "",
                                        "acknowledged": terms.ACK_ITEMS})
        out["signature"] = signed
        out["terms"] = {"version": tdoc.get("version"), "sha256": tdoc.get("sha256")}
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (out["bookingId"],)).fetchone()
        c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
        v = conn.execute("SELECT * FROM vehicles WHERE id=?", (b["vehicle_id"],)).fetchone()
        start = datetime.fromisoformat(b["scheduled_start"]) if b["scheduled_start"] else None
        ctx2 = email_ctx(conn, body, out, body["client"], start)
        ctx2["vehicle"] = (v["model"] if v and v["model"] else "BMW")
        # The invoice is DRAFTED, not sent: prices vary by car, so the owner
        # opens the dashboard, adjusts the lines, and hits "Send invoice".
        inv = booking.create_invoice(conn, out["bookingId"], out["proposal"]["proposalId"],
                                     "deposit" if out["quote"]["custom"] else "balance")
        if inv["amountDue"] <= 0:
            # a by-VIN quote has no price yet — no invoice until the owner sets one
            inv = None
        conn.execute("UPDATE bookings SET status='confirmed', updated_at=datetime('now') WHERE id=?",
                     (out["bookingId"],))
        emails.queue(conn, c["email"], "booking_confirmed", ctx2, out["bookingId"])
        if start:
            emails.queue(conn, c["email"], "day_before", ctx2, out["bookingId"],
                         when=(start - timedelta(days=1)).replace(hour=17, minute=0))
            emails.queue(conn, c["email"], "review_request", ctx2, out["bookingId"],
                         when=start + timedelta(days=1, hours=20))
        emails.cancel_pending(conn, out["bookingId"], ["proposal_reminder"])
        notify_owner(conn, "owner_signed", {**ctx2, "client": body["client"].get("name", ""),
                                            "code": out["code"]}, out["bookingId"])
        out["depositInvoice"] = ({"number": inv["number"], "amountDue": inv["amountDue"],
                                  "status": "draft",
                                  "link": f"{BASE_URL}/i/{inv['publicToken']}"} if inv else None)
        out["emailsQueued"] = (sent if isinstance(sent, int) else len(sent)) + 3
        out["links"] = {"proposal": f"{BASE_URL}/p/{out['proposal']['publicToken']}",
                        "invoice": out["depositInvoice"]["link"] if out["depositInvoice"] else None}
        out["slot"] = out["quote"]["slot"]
        out["travel"] = out["quote"]["travel"]
    return out


def get_proposal(tok: str) -> dict:
    with dbmod.db() as conn:
        p = conn.execute("SELECT * FROM proposals WHERE public_token=?", (tok,)).fetchone()
        if not p:
            raise LookupError("not found")
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (p["booking_id"],)).fetchone()
        c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
        v = conn.execute("SELECT * FROM vehicles WHERE id=?", (b["vehicle_id"],)).fetchone()
        tdoc = terms.active_terms(conn)
        if p["status"] in ("sent", "viewed"):
            conn.execute("UPDATE proposals SET status='viewed', viewed_at=COALESCE(viewed_at, datetime('now'))"
                         " WHERE id=?", (p["id"],))
        return {
            "proposal": {k: p[k] for k in ("number", "status", "expires_at", "signed_at", "signature_name",
                                           "terms_version")},
            "lines": json.loads(p["lines_json"]),
            "totals": json.loads(p["totals_json"]),
            "client": {k: c[k] for k in ("name", "email", "phone", "address", "city", "state", "zip")},
            "vehicle": {k: v[k] for k in ("vin", "year", "model", "engine")},
            "booking": {"code": b["code"], "scheduled_start": b["scheduled_start"],
                        "travel_miles": b["travel_miles"], "travel_fee": b["travel_fee"]},
            "terms": {"version": tdoc.get("version"), "body": tdoc.get("body"), "sha256": tdoc.get("sha256")},
            "shop": catalog()["shop"],
            "custom": bool(booking.meta_get(conn, "booking", p["booking_id"], "custom", False)),
            "answers": booking.meta_get(conn, "booking", b["id"], "answers", {}),
            "questions": booking.meta_get(conn, "booking", b["id"], "questions", []),
            "travel": json.loads(b["travel_json"] or "{}"),
            "acknowledgments": terms.ACK_ITEMS,
        }


def sign_proposal(tok: str, body: dict, ip: str, ua: str) -> dict:
    if not body.get("name") or len(str(body["name"]).strip()) < 2:
        raise ValueError("Type your full name to sign")
    if not body.get("consent") or not body.get("acknowledged"):
        raise ValueError("Check the box to agree to the Terms and Conditions before signing")
    with dbmod.db() as conn:
        p = conn.execute("SELECT * FROM proposals WHERE public_token=?", (tok,)).fetchone()
        if not p:
            raise LookupError("not found")
        sig = booking.sign_proposal(conn, p["id"], {"name": body["name"], "image": body.get("image"),
                                                    "ip": ip, "ua": ua,
                                                    "acknowledged": terms.ACK_ITEMS})
        totals = json.loads(p["totals_json"])
        is_custom = bool(booking.meta_get(conn, "booking", p["booking_id"], "custom", False))
        inv = booking.create_invoice(conn, p["booking_id"], p["id"], "deposit") if is_custom else None
        if inv is None:
            # Standard menu job: signed is booked. Balance invoice is issued on completion.
            conn.execute("UPDATE bookings SET status='confirmed', updated_at=datetime('now') WHERE id=?",
                         (p["booking_id"],))
        cat = catalog()
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (p["booking_id"],)).fetchone()
        c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
        emails.cancel_pending(conn, p["booking_id"], ["proposal_reminder"])
        b2 = conn.execute("SELECT * FROM bookings WHERE id=?", (p["booking_id"],)).fetchone()
        start = datetime.fromisoformat(b2["scheduled_start"]) if b2["scheduled_start"] else None
        v = conn.execute("SELECT * FROM vehicles WHERE id=?", (b2["vehicle_id"],)).fetchone()
        lines = json.loads(p["lines_json"])
        ctx = {
            "first_name": c["name"].split()[0], "email": c["email"], "phone": cat["shop"]["phone"],
            "vehicle": (v["model"] if v and v["model"] else "BMW"), "number": p["number"],
            "summary": money_lines(lines), "travel_line": "",
            "date": start.strftime("%a %b %d") if start else "", "time": start.strftime("%I:%M %p").lstrip("0") if start else "",
            "address": f"{c['address'] or ''}, {c['city'] or ''} {c['state'] or 'NJ'}",
            "balance": f"{totals['balance']:.2f}", "deposit": f"{totals['deposit']:.2f}",
            "scheduled_start": b2["scheduled_start"] or "",
            "service": ", ".join(l["name"] for l in lines if l["kind"] == "service"),
            "total": f"{totals['total']:.2f}",
        }
        if inv:
            emails.queue(conn, c["email"], "proposal_signed",
                         {**ctx, "invoice": inv["number"], "link": f"{BASE_URL}/i/{inv['publicToken']}"},
                         p["booking_id"])
        else:
            emails.queue(conn, c["email"], "booking_confirmed", ctx, p["booking_id"])
            if start:
                emails.queue(conn, c["email"], "day_before", ctx, p["booking_id"],
                             when=(start - timedelta(days=1)).replace(hour=17, minute=0))
                emails.queue(conn, c["email"], "review_request", ctx, p["booking_id"],
                             when=start + timedelta(days=1, hours=20))
        notify_owner(conn, "owner_signed", {**ctx, "client": c["name"], "code": b2["code"]}, p["booking_id"])
        return {"signed": True, **sig, "depositRequired": bool(inv),
                "invoice": ({"number": inv["number"], "amountDue": inv["amountDue"],
                             "link": f"{BASE_URL}/i/{inv['publicToken']}"} if inv else None),
                "bookingStatus": "confirmed"}


def get_invoice(tok: str) -> dict:  # raises LookupError -> 404
    """Everything the client sees on their invoice: their info, the car, the work,
    the money, the terms they signed, and their signature."""
    cat = catalog()
    with dbmod.db() as conn:
        i = conn.execute("SELECT * FROM invoices WHERE public_token=?", (tok,)).fetchone()
        if not i:
            raise LookupError("not found")
        pays = dbmod.rows(conn.execute("SELECT amount, kind, method, received_at FROM payments"
                                       " WHERE invoice_id=? ORDER BY id", (i["id"],)))
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (i["booking_id"],)).fetchone()
        c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
        v = conn.execute("SELECT * FROM vehicles WHERE id=?", (b["vehicle_id"],)).fetchone()
        p = conn.execute("SELECT * FROM proposals WHERE booking_id=? ORDER BY id DESC LIMIT 1",
                         (b["id"],)).fetchone()
        totals = json.loads(i["totals_json"] or "{}")
        lines = totals.get("lines")
        if not lines and p:
            lines = json.loads(p["lines_json"] or "[]")
        terms_body = ""
        if p and p["terms_version"]:
            row = conn.execute("SELECT body FROM templates WHERE kind='terms' AND version=?",
                               (p["terms_version"],)).fetchone()
            terms_body = row["body"] if row else ""
        questions = []
        mq = conn.execute("SELECT value FROM meta WHERE entity='booking' AND entity_id=? AND key='questions'",
                          (b["id"],)).fetchone()
        ma = conn.execute("SELECT value FROM meta WHERE entity='booking' AND entity_id=? AND key='answers'",
                          (b["id"],)).fetchone()
        if mq and ma:
            try:
                for q in json.loads(mq["value"]):
                    if q.get("type") == "note":
                        continue
                    ans = json.loads(ma["value"]).get(q["id"], "")
                    if ans:
                        questions.append({"question": q.get("label"), "answer": ans})
            except Exception:
                pass
        return {
            "invoice": {"number": i["number"], "status": i["status"], "due_at": i["due_at"],
                        "created_at": i["created_at"], "kind": totals.get("kind", "balance"),
                        "note": totals.get("note", "")},
            "booking": b["code"], "scheduledStart": b["scheduled_start"],
            "client": {"name": c["name"], "email": c["email"], "phone": c["phone"],
                       "address": ", ".join(x for x in (c["address"], c["city"], c["state"], c["zip"]) if x)},
            "vehicle": {"vin": v["vin"] if v else "", "model": v["model"] if v else "",
                        "year": v["year"] if v else ""},
            "lines": lines or [], "questions": questions,
            "totals": totals, "payments": pays, "paid": round(sum(p["amount"] for p in pays), 2),
            "signature": ({"name": p["signature_name"], "image": p["signature_image"],
                           "signedAt": p["signed_at"], "ip": p["signature_ip"],
                           "hash": p["signed_hash"], "proposal": p["number"],
                           "termsVersion": p["terms_version"]} if p else None),
            "terms": {"version": p["terms_version"] if p else "", "body": terms_body},
            "shop": {k: cat["shop"].get(k) for k in ("name", "phone", "email", "baseAddress",
                                                     "hoursLabel", "accepts", "logo", "theme")},
        }


def availability(date: str, hours_needed: float | None = None) -> dict:
    """Every start time on the half hour inside the shop's hours, marked free or taken.

    A slot is blocked when the job would run into another job already on the
    calendar — the booked job reserves its own length plus the drive/cleanup
    buffer, so two clients can never be promised overlapping time.
    """
    cat = catalog()
    shop = cat["shop"]
    hours = shop.get("hours") or {}
    need = float(hours_needed or 2.0)
    try:
        day = datetime.fromisoformat(str(date).strip())
    except (ValueError, TypeError):
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    windows = hours.get(str((day.weekday() + 1) % 7), [])  # python Mon=0, our map 0=Sun
    with dbmod.db() as conn:
        taken = dbmod.rows(conn.execute(
            "SELECT scheduled_start, scheduled_end FROM bookings WHERE date(scheduled_start)=?"
            " AND status NOT IN ('cancelled')", (date,)))
    busy = []
    for t in taken:
        st = datetime.fromisoformat(t["scheduled_start"])
        if t["scheduled_end"]:
            en = datetime.fromisoformat(t["scheduled_end"])
        else:
            en = st + timedelta(hours=need)
        busy.append((st, en))

    slots = []
    for start_s, end_s in windows:
        sh, sm = [int(x) for x in start_s.split(":")]
        eh, em = [int(x) for x in end_s.split(":")]
        cur = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
        close = day.replace(hour=eh, minute=em, second=0, microsecond=0)
        while cur < close:
            end = cur + timedelta(hours=need)
            clash = any(cur < b_en and b_st < end for b_st, b_en in busy)
            fits = end <= close
            slots.append({"start": cur.isoformat(timespec="minutes"),
                          "end": end.isoformat(timespec="minutes"),
                          "label": cur.strftime("%-I:%M %p") if os.name != "nt" else cur.strftime("%I:%M %p").lstrip("0"),
                          "available": (not clash) and fits,
                          "reason": "" if (not clash and fits) else ("booked" if clash else "closes")})
            cur = cur + timedelta(minutes=30)
    return {"date": date, "hours": [f"{w[0]}-{w[1]}" for w in windows], "closed": not windows,
            "hoursLabel": shop.get("hoursLabel"), "jobHours": need, "slots": slots,
            "openCount": sum(1 for x in slots if x["available"])}


# ------------------------------------------------------------------ admin

def admin_summary() -> dict:
    with dbmod.db() as conn:
        counts = {r["status"]: r["n"] for r in dbmod.rows(conn.execute(
            "SELECT status, COUNT(*) n FROM bookings GROUP BY status"))}
        money = dbmod.rows(conn.execute(
            "SELECT i.status, COUNT(*) n, i.totals_json FROM invoices i")) or []
        paid = 0.0
        outstanding = 0.0
        for m in money:
            due = json.loads(m["totals_json"] or "{}").get("amountDue", 0)
            if m["status"] == "paid":
                paid += due
            else:
                outstanding += due
        upcoming = dbmod.rows(conn.execute(
            "SELECT b.code, b.scheduled_start, b.status, c.name, v.model FROM bookings b"
            " JOIN clients c ON c.id=b.client_id LEFT JOIN vehicles v ON v.id=b.vehicle_id"
            " WHERE b.scheduled_start >= ? ORDER BY b.scheduled_start LIMIT 10",
            (datetime.now().isoformat(timespec="minutes"),)))
        queue = dbmod.rows(conn.execute(
            "SELECT template, subject, scheduled_for FROM emails WHERE status='queued'"
            " ORDER BY scheduled_for LIMIT 10"))
    return {"bookingsByStatus": counts, "collected": round(paid, 2),
            "outstanding": round(outstanding, 2), "upcoming": upcoming, "emailQueue": queue}


def admin_bookings(status: str | None = None, limit: int = 100) -> dict:
    with dbmod.db() as conn:
        q = ("SELECT b.id, b.code, b.status, b.scheduled_start, b.job_hours, b.travel_miles, b.travel_fee,"
             " b.created_at, c.name client, c.email, c.phone, c.city, v.vin, v.model,"
             " (SELECT number FROM proposals p WHERE p.booking_id=b.id ORDER BY p.id DESC LIMIT 1) proposal,"
             " (SELECT totals_json FROM proposals p WHERE p.booking_id=b.id ORDER BY p.id DESC LIMIT 1) totals,"
             " (SELECT COALESCE(SUM(amount),0) FROM payments pay JOIN invoices i2 ON i2.id=pay.invoice_id"
             "  WHERE i2.booking_id=b.id) paid,"
             " (SELECT COUNT(*) FROM emails e WHERE e.booking_id=b.id AND e.status='queued') queued_emails"
             " FROM bookings b JOIN clients c ON c.id=b.client_id LEFT JOIN vehicles v ON v.id=b.vehicle_id")
        params: list = []
        if status and status != "all":
            q += " WHERE b.status=?"
            params.append(status)
        q += " ORDER BY COALESCE(b.scheduled_start, b.created_at) DESC LIMIT ?"
        params.append(limit)
        out = []
        for r in dbmod.rows(conn.execute(q, params)):
            tot = json.loads(r.pop("totals") or "{}")
            r["total"] = tot.get("total", 0)
            r["balanceDue"] = round(max(0, tot.get("total", 0) - r["paid"]), 2)
            out.append(r)
        return {"bookings": out}


def admin_booking(booking_id: int) -> dict:
    with dbmod.db() as conn:
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not b:
            raise LookupError("booking not found")
        c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
        v = conn.execute("SELECT * FROM vehicles WHERE id=?", (b["vehicle_id"],)).fetchone()
        props = dbmod.rows(conn.execute("SELECT * FROM proposals WHERE booking_id=? ORDER BY id DESC", (booking_id,)))
        invs = dbmod.rows(conn.execute("SELECT * FROM invoices WHERE booking_id=? ORDER BY id DESC", (booking_id,)))
        pays = dbmod.rows(conn.execute(
            "SELECT pay.* FROM payments pay JOIN invoices i ON i.id=pay.invoice_id WHERE i.booking_id=?"
            " ORDER BY pay.id DESC", (booking_id,)))
        mails = dbmod.rows(conn.execute(
            "SELECT id, template, subject, status, scheduled_for, sent_at, error FROM emails WHERE booking_id=?"
            " ORDER BY id DESC LIMIT 40", (booking_id,)))
        for p in props:
            p["lines"] = json.loads(p.pop("lines_json") or "[]")
            p["totals"] = json.loads(p.pop("totals_json") or "{}")
        for i in invs:
            i["totals"] = json.loads(i.pop("totals_json") or "{}")
        return {"booking": dict(b), "client": dict(c), "vehicle": dict(v or {}),
                "answers": booking.meta_get(conn, "booking", booking_id, "answers", {}),
                "custom": booking.meta_get(conn, "booking", booking_id, "custom", False),
                "proposals": props, "invoices": invs, "payments": pays, "emails": mails,
                "audit": dbmod.rows(conn.execute("SELECT * FROM audit WHERE entity IN ('booking','proposal',"
                                                 "'invoice') ORDER BY id DESC LIMIT 60"))}


def handle_admin(action: str, body: dict) -> dict:
    cat = catalog()
    with dbmod.db() as conn:
        if action == "summary":
            return admin_summary()
        if action == "bookings":
            return admin_bookings(body.get("status"), int(body.get("limit") or 100))
        if action == "booking":
            return admin_booking(int(body["bookingId"]))
        if action == "proposal.resend":
            pr = conn.execute("SELECT p.*, b.client_id, c.email, c.name, b.id bid, v.model FROM proposals p"
                              " JOIN bookings b ON b.id=p.booking_id JOIN clients c ON c.id=b.client_id"
                              " LEFT JOIN vehicles v ON v.id=b.vehicle_id WHERE p.id=?",
                              (int(body["proposalId"]),)).fetchone()
            if not pr:
                raise LookupError("proposal not found")
            totals = json.loads(pr["totals_json"])
            start = conn.execute("SELECT scheduled_start FROM bookings WHERE id=?", (pr["bid"],)).fetchone()["scheduled_start"]
            emails.queue(conn, pr["email"], "quote_for_approval",
                         {"first_name": pr["name"].split()[0], "number": pr["number"],
                          "vehicle": pr["model"] or "BMW", "summary": money_lines(json.loads(pr["lines_json"])),
                          "travel_line": "", "total": f"{totals.get('total', 0):.2f}",
                          "link": f"{BASE_URL}/p/{pr['public_token']}", "phone": catalog()["shop"]["phone"]},
                         pr["bid"])
            return {"queued": True, "link": f"{BASE_URL}/p/{pr['public_token']}"}
        if action == "invoice.create":
            return booking.create_manual_invoice(conn, int(body["bookingId"]), float(body["amount"]),
                                                 body.get("kind", "payment"), body.get("description"))
        if action == "invoice.email":
            inv = conn.execute("SELECT i.*, b.client_id, c.email, c.name FROM invoices i"
                               " JOIN bookings b ON b.id=i.booking_id JOIN clients c ON c.id=b.client_id"
                               " WHERE i.id=?", (int(body["invoiceId"]),)).fetchone()
            if not inv:
                raise LookupError("invoice not found")
            totals = json.loads(inv["totals_json"])
            emails.queue(conn, inv["email"], "invoice_manual",
                         {"first_name": inv["name"].split()[0], "invoice": inv["number"],
                          "amount": f"{totals['amountDue']:.2f}",
                          "summary": totals.get("description", "Service"),
                          "link": f"{BASE_URL}/i/{inv['public_token']}"}, inv["booking_id"])
            conn.execute("UPDATE invoices SET status=CASE WHEN status='open' THEN 'sent' ELSE status END WHERE id=?",
                         (inv["id"],))
            booking.audit(conn, "invoice.emailed", "invoice", inv["id"], inv["number"], "owner")
            return {"queued": True, "link": f"{BASE_URL}/i/{inv['public_token']}"}
        if action == "email.send":   # owner writes a one-off email to a booking's client
            b = conn.execute("SELECT b.*, c.email, c.name FROM bookings b JOIN clients c ON c.id=b.client_id"
                             " WHERE b.id=?", (int(body["bookingId"]),)).fetchone()
            if not b:
                raise LookupError("booking not found")
            eid = emails.queue(conn, b["email"], "custom", {"first_name": b["name"].split()[0]}, b["id"])
            conn.execute("UPDATE emails SET subject=?, body=?, template='custom' WHERE id=?",
                         (body.get("subject", "Bimmer House Calls"), body.get("body", ""), eid))
            return {"queued": True, "emailId": eid}
        if action == "reschedule":
            bid = int(body["bookingId"])
            start = datetime.fromisoformat(body["scheduledStart"])
            hours = body.get("hours") or 2.5
            end = start + timedelta(hours=float(hours))
            conn.execute("UPDATE bookings SET scheduled_start=?, scheduled_end=?, updated_at=datetime('now')"
                         " WHERE id=?", (start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), bid))
            b = conn.execute("SELECT b.*, c.email, c.name, v.model FROM bookings b JOIN clients c ON c.id=b.client_id"
                             " LEFT JOIN vehicles v ON v.id=b.vehicle_id WHERE b.id=?", (bid,)).fetchone()
            emails.queue(conn, b["email"], "reschedule",
                         {"first_name": b["name"].split()[0], "vehicle": b["model"] or "BMW",
                          "date": start.strftime("%A %b %d"), "time": start.strftime("%I:%M %p").lstrip("0")}, bid)
            booking.audit(conn, "booking.rescheduled", "booking", bid, body["scheduledStart"], "owner")
            return {"ok": True, "scheduled_start": start.isoformat(timespec="minutes")}
        if action == "cancel":
            bid = int(body["bookingId"])
            conn.execute("UPDATE bookings SET status='cancelled', updated_at=datetime('now') WHERE id=?", (bid,))
            b = conn.execute("SELECT b.*, c.email, c.name FROM bookings b JOIN clients c ON c.id=b.client_id"
                             " WHERE b.id=?", (bid,)).fetchone()
            emails.cancel_pending(conn, bid)
            emails.queue(conn, b["email"], "cancellation",
                         {"first_name": b["name"].split()[0], "code": b["code"]}, bid)
            booking.audit(conn, "booking.cancelled", "booking", bid, b["code"], "owner")
            return {"ok": True}
        if action == "proposal.manual":   # owner builds/edits a proposal for a booking
            bid = int(body["bookingId"])
            q = {"lines": body["lines"], "totals": body["totals"]}
            return booking.create_proposal(conn, bid, q)
        if action == "invoice.create":
            return booking.create_invoice(conn, int(body["bookingId"]), int(body.get("proposalId") or 0) or None,
                                          body.get("kind", "deposit"))
        if action == "invoices":
            rows = dbmod.rows(conn.execute(
                "SELECT i.*, c.name client, c.email, b.code, b.scheduled_start"
                " FROM invoices i JOIN bookings b ON b.id=i.booking_id"
                " JOIN clients c ON c.id=b.client_id ORDER BY i.id DESC LIMIT 200"))
            out = []
            for r in rows:
                t = json.loads(r["totals_json"] or "{}")
                paid = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?",
                                    (r["id"],)).fetchone()["s"]
                out.append({"id": r["id"], "number": r["number"], "status": r["status"],
                            "client": r["client"], "email": r["email"], "code": r["code"],
                            "kind": t.get("kind", "balance"), "due_at": r["due_at"],
                            "amountDue": t.get("amountDue", 0), "total": t.get("total", 0),
                            "taxRate": t.get("taxRate", 0), "note": t.get("note", ""),
                            "lines": t.get("lines") or [], "paid": paid,
                            "draft": r["status"] == "draft",
                            "locked": paid > 0, "link": f"{BASE_URL}/i/{r['public_token']}"})
            return {"invoices": out}
        if action == "invoice.update":
            res = booking.update_invoice(conn, int(body["invoiceId"]), body.get("lines") or [],
                                         body.get("note", ""), body.get("taxRate"))
            conn.commit()  # release the write lock before queueing the email
            if body.get("send"):
                # "Save & send" in one step: price it your way, then email it
                inv2 = conn.execute("SELECT * FROM invoices WHERE id=?",
                                    (int(body["invoiceId"]),)).fetchone()
                res["send"] = handle_admin("invoice.send", {"invoiceId": inv2["id"]})
            return res
        if action == "invoice.send":
            inv = conn.execute("SELECT * FROM invoices WHERE id=?", (int(body["invoiceId"]),)).fetchone()
            if not inv:
                raise KeyError("invoice not found")
            b = conn.execute("SELECT * FROM bookings WHERE id=?", (inv["booking_id"],)).fetchone()
            c = conn.execute("SELECT * FROM clients WHERE id=?", (b["client_id"],)).fetchone()
            t = json.loads(inv["totals_json"] or "{}")
            lines = t.get("lines") or []
            summary = "\n".join(f"• {l['name']} x{l.get('qty',1)} — ${l.get('total', 0):.2f}" for l in lines)
            emails.queue(conn, c["email"], "invoice_sent",
                         {"first_name": c["name"].split()[0], "email": c["email"],
                          "vehicle": "BMW", "invoice": inv["number"],
                          "amount": f"{t.get('amountDue', 0):.2f}",
                          "summary": summary or "Service",
                          "link": f"{BASE_URL}/i/{inv['public_token']}",
                          "phone": catalog()["shop"]["phone"],
                          "date": (b["scheduled_start"] or "")[:10]}, inv["booking_id"])
            conn.execute("UPDATE invoices SET status=CASE WHEN status='draft' THEN 'open' ELSE status END WHERE id=?",
                         (inv["id"],))
            return {"sent": True, "number": inv["number"], "to": c["email"]}
        if action == "email.flush":
            from app.services import mailer as mailer_mod
            return mailer_mod.drain(limit=int((body or {}).get("limit", 50)))
        if action == "email.outbox":
            rows = dbmod.rows(conn.execute(
                "SELECT id, to_email, template, status, error, scheduled_for, created_at"
                " FROM emails ORDER BY id DESC LIMIT 40"))
            return {"emails": rows}
        if action == "email.diagnose":
            from app.services import mailer as mailer_mod
            return mailer_mod.diagnose()
        if action == "email.send_test":
            from app.services import mailer as mailer_mod
            to = (body or {}).get("to") or cat["shop"].get("email")
            if not to:
                raise ValueError("No address to send to")
            d = mailer_mod.diagnose()
            if d["sender"] == "none":
                return {"sent": False, "why": d["problem"]}
            try:
                how = mailer_mod.send_now(to, "Bimmer House Calls — test email",
                                          "<p>This is a test from your backend. If you are reading it, "
                                          "client email works.</p>")
            except Exception as exc:  # noqa: BLE001
                return {"sent": False, "why": f"{type(exc).__name__}: {exc}"}
            return {"sent": how != "queued", "how": how, "to": to}
        if action == "database.reset":
            if (body or {}).get("confirm") != "RESET":
                raise ValueError("Type RESET to confirm - this deletes every test client, booking and invoice")
            counts = booking.reset_demo_data(conn)
            return {"cleared": counts, "note": "Catalog, terms, theme and admin key kept"}
        if action == "archive.run":
            from app.services import archive as archive_mod
            return archive_mod.run()
        if action == "payment.record":
            res = booking.record_payment(conn, int(body["invoiceId"]), float(body["amount"]),
                                         body.get("method", "card"), body.get("processor", "manual"),
                                         body.get("ref"), body.get("note", ""))
            inv = conn.execute("SELECT * FROM invoices WHERE id=?", (int(body["invoiceId"]),)).fetchone()
            emails.queue(conn, catalog()["shop"]["email"], "owner_paid",
                         {"amount": f"{float(body['amount']):.2f}", "invoice": inv["number"],
                          "method": body.get("method", "card"), "balance": f"{res['balance']:.2f}"})
            return res
        if action == "booking.status":
            conn.execute("UPDATE bookings SET status=?, updated_at=datetime('now') WHERE id=?",
                         (body["status"], int(body["bookingId"])))
            booking.audit(conn, "booking.status", "booking", int(body["bookingId"]), body["status"], "owner")
            return {"ok": True}
        if action == "email.retry":
            conn.execute("UPDATE emails SET status='queued', error=NULL WHERE id=?", (int(body["id"]),))
            return {"ok": True}
        if action == "quote.override":    # owner sets the final price on a line
            p = conn.execute("SELECT lines_json, id, booking_id FROM proposals WHERE id=?",
                             (int(body["proposalId"]),)).fetchone()
            lines = json.loads(p["lines_json"])
            for l in lines:
                if l["id"] == body["lineId"]:
                    l["unit"] = float(body["unit"])
                    l["overridden"] = True
            conn.execute("UPDATE proposals SET lines_json=? WHERE id=?", (json.dumps(lines), p["id"]))
            return {"ok": True, "lines": lines}
        if action == "vehicles":
            return {"vehicles": dbmod.rows(conn.execute(
                "SELECT v.*, c.name client FROM vehicles v LEFT JOIN clients c ON c.id=v.client_id"
                " ORDER BY v.id DESC LIMIT 100"))}
        raise KeyError(f"unknown admin action: {action}")


# ------------------------------------------------------------------ HTTP plumbing


PRIVACY_MD = """# Privacy Policy

**{shop}** — mobile BMW service. Based in {base}.

## What we collect

- Your name, phone number, email address and service address
- Your vehicle's VIN, model and year
- The work you ask us to do, and any notes you give us
- Your signature on our service terms, the time you signed, and the IP address you signed from
- Records of quotes, invoices and payments

## Why we collect it

To quote the work, travel to you, do the work, invoice you, and keep a record of
what was agreed. We also use your email and phone to send you booking
confirmations, reminders and invoices.

## Who we share it with

Nobody. We do not sell, rent or trade your information. It is not shared with
advertisers or data brokers.

We use Google to send our email. Google processes the messages we send and
receives your email address as the recipient.

## How long we keep it

Booking and invoice records are kept for seven years, which is what tax and
warranty records require. You can ask us to delete anything else at any time.

## Your choices

Email **{email}** or call **{phone}** to:

- Ask what we hold about you
- Correct anything that is wrong
- Ask us to delete your information
- Stop receiving reminders and follow-up emails

## Security

Access to your information is limited to the owner of {shop}. Payment card
numbers are never stored — we take payment by Zelle, cash or check.

## Contact

{shop} · {email} · {phone}

_Last updated 2026._
"""


def md_to_html(md: str, shop_name: str) -> str:
    """Small, safe markdown renderer for the public terms/privacy pages."""
    import html as htmllib
    out, in_list, para = [], False, []
    lines = md.splitlines()
    merged = []
    for ln in lines:
        if not ln.strip():
            if para:
                merged.append(" ".join(para))
                para = []
            merged.append("")
        elif ln.startswith(("# ", "## ")) or ln.lstrip().startswith("- "):
            if para:
                merged.append(" ".join(para))
                para = []
            merged.append(ln)
        else:
            para.append(ln.strip())
    if para:
        merged.append(" ".join(para))
    for raw in merged:
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{htmllib.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{htmllib.escape(line[3:])}</h2>")
        elif line.lstrip().startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{htmllib.escape(line.lstrip()[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            text = htmllib.escape(line)
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
            out.append(f"<p>{text}</p>")
    if in_list:
        out.append("</ul>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{htmllib.escape(shop_name)}</title>"
            "<style>body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
            "max-width:760px;margin:0 auto;padding:36px 20px 80px;color:#0B0B0D;line-height:1.6}"
            "h1{font-size:30px;margin:0 0 18px}h2{font-size:19px;margin:30px 0 8px}"
            "li{margin:4px 0}p{margin:9px 0}"
            "a{color:#0B0B0D}footer{margin-top:44px;padding-top:16px;border-top:1px solid #e5e8ec;"
            "font-size:13px;color:#5b6470}</style></head><body>" + "".join(out) +
            f"<footer>{htmllib.escape(shop_name)} · mobile BMW service</footer></body></html>")


class Handler(BaseHTTPRequestHandler):
    server_version = "BHC/1.0"

    def _cors(self):
        origin = self.headers.get("Origin", "")
        allow = origin if origin in CORS_ORIGINS else CORS_ORIGINS[0]
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, data, code=200):
        raw = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _file_bytes(self, raw, ctype, code=200):
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        return None

    def _file(self, path, code=200):
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return self._json({"error": "not found"}, 404)
        ext = os.path.splitext(path)[1].lower()
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                 ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}.get(ext, "text/plain")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _run_job(self):
        """Token-protected jobs an outside scheduler can call (free hosts have no cron)."""
        u = urlparse(self.path)
        job = u.path.split("/api/run/", 1)[1]
        if not self._admin_ok():
            return self._json({"error": "unauthorized"}, 401)
        if job == "mailer":
            from app.services import mailer
            return self._json(mailer.drain())
        if job == "digest":
            from app.services import mailer
            return self._json(mailer.digest())
        if job == "archive":
            from app.services import archive
            return self._json(archive.run())
        if job == "automation":
            from app.services import automation
            return self._json(automation.run())
        return self._json({"error": "unknown job"}, 404)

    def _stored_key(self) -> str:
        with dbmod.db() as conn:
            return booking.meta_get(conn, "settings", 0, "admin_key") or ""

    def _admin_ok(self) -> bool:
        """Locked by default. The key comes from BHC_ADMIN_KEY, or from the database
        (set with `./bhc.sh password`), so it works the same locally and on a server."""
        key = os.environ.get("BHC_ADMIN_KEY") or self._stored_key()
        if not key:
            return False
        given = self.headers.get("X-Admin-Key") or ""
        return hmac.compare_digest(given, key)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path.startswith("/api/run/"):
                return self._run_job()
            if u.path == "/api/health":
                return self._json({"ok": True, "time": datetime.now().isoformat(timespec="seconds"),
                                   "adminLocked": self._admin_ok.__self__ is not None and bool(
                                       os.environ.get("BHC_ADMIN_KEY") or self._stored_key())})
            if u.path == "/api/terms":
                with dbmod.db() as conn:
                    tdoc = terms.active_terms(conn)
                return self._json({"version": tdoc.get("version"), "body": tdoc.get("body"),
                                   "sha256": tdoc.get("sha256"), "acknowledgments": terms.ACK_ITEMS})
            if u.path == "/api/catalog":
                cat = catalog()
                return self._json({"categories": cat["categories"], "addons": cat["addons"],
                                   "packages": cat["packages"], "travel": cat["travel"],
                                   "shop": cat["shop"], "theme": cat["shop"].get("theme", {}),
                                   "hours": cat["shop"].get("hours", {}),
                                   "hoursLabel": cat["shop"].get("hoursLabel", ""),
                                   "acknowledgments": terms.ACK_ITEMS})
            if u.path == "/api/availability":
                hrs = q.get("hours", [None])[0]
                return self._json(availability(
                    q.get("date", [datetime.now().date().isoformat()])[0],
                    float(hrs) if hrs else None))
            m = re.fullmatch(r"/api/p/([\w\-]+)", u.path)
            if m:
                return self._json(get_proposal(m.group(1)))
            m = re.fullmatch(r"/api/i/([\w\-]+)", u.path)
            if m:
                return self._json(get_invoice(m.group(1)))
            if u.path.startswith("/api/admin/"):
                if not self._admin_ok():
                    return self._json({"error": "unauthorized"}, 401)
                return self._json(handle_admin(u.path.rsplit("/", 1)[-1], {}))
            # client portal pages
            m = re.fullmatch(r"/p/([\w\-]+)", u.path)
            if m:
                return self._file(os.path.join(STATIC, "proposal.html"))
            m = re.fullmatch(r"/i/([\w\-]+)", u.path)
            if m:
                # a bad or expired link should say so, not show a broken page
                try:
                    get_invoice(m.group(1))
                except LookupError:
                    return self._file(os.path.join(STATIC, "invoice.html"), 404)
                return self._file(os.path.join(STATIC, "invoice.html"))
            if u.path == "/admin/database.sqlite3":
                if not self._admin_ok():
                    return self._json({"error": "unauthorized"}, 401)
                path = dbmod.DB_PATH
                with open(path, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="bhc-{datetime.now():%Y%m%d-%H%M}.sqlite3"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            if u.path in ("/oauth/start", "/oauth/connect"):
                import urllib.parse as _up
                cid = os.environ.get("BHC_GOOGLE_CLIENT_ID", "")
                red = os.environ.get("BHC_OAUTH_REDIRECT", "")
                if not (cid and red):
                    return self._file_bytes("<h3>Set BHC_GOOGLE_CLIENT_ID and BHC_OAUTH_REDIRECT first.</h3>",
                                            "text/html; charset=utf-8", 400)
                url = ("https://accounts.google.com/o/oauth2/v2/auth?"
                       + _up.urlencode({"client_id": cid, "redirect_uri": red,
                                        "response_type": "code",
                                        "scope": "https://www.googleapis.com/auth/gmail.send",
                                        "access_type": "offline", "prompt": "consent"}))
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
                return None
            if u.path in ("/oauth/callback", "/oauth/connect-callback"):
                from app.services import mailer as mailer_mod
                q = parse_qs(urlparse(self.path).query)
                code = (q.get("code") or [""])[0]
                if not code:
                    return self._file_bytes("<h3>No code returned.</h3><p>"
                                            + (q.get("error") or ["unknown"])[0] + "</p>",
                                            "text/html; charset=utf-8", 400)
                try:
                    tok = mailer_mod.exchange_code(code)
                except Exception as exc:  # noqa: BLE001
                    return self._file_bytes(f"<h3>Exchange failed</h3><pre>{exc}</pre>",
                                            "text/html; charset=utf-8", 400)
                rt = tok.get("refresh_token", "")
                page = ("<!doctype html><meta charset='utf-8'><title>Gmail connected</title>"
                        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
                        "max-width:720px;margin:40px auto;padding:0 18px;color:#0B0B0D}"
                        "code{display:block;background:#f6f8fa;padding:12px;border-radius:8px;"
                        "word-break:break-all;font-size:13px;margin:10px 0}</style>"
                        "<h2>Gmail connected</h2>"
                        + ("<p>Copy this into Render → Environment as "
                           "<b>BHC_GOOGLE_REFRESH_TOKEN</b>:</p><code>" + rt + "</code>"
                           "<p>Then delete the temporary OAuth variables and redeploy.</p>"
                           if rt else
                           "<p>No refresh token came back. Remove the app's access at "
                           "<a href='https://myaccount.google.com/permissions'>myaccount.google.com/permissions</a> "
                           "and try again.</p>"))
                return self._file_bytes(page, "text/html; charset=utf-8")
            if u.path in ("/terms", "/privacy"):
                from app.services import terms as terms_mod
                cat = pricing.load_catalog()
                shop = cat["shop"]
                if u.path == "/terms":
                    body_md = terms_mod.render_terms(cat)
                else:
                    body_md = PRIVACY_MD.format(
                        shop=shop.get("name", "Bimmer House Calls"),
                        email=shop.get("email", ""),
                        phone=shop.get("phone", ""),
                        base=shop.get("baseAddress", "Surf City, NJ"))
                html = md_to_html(body_md, shop.get("name", "Bimmer House Calls"))
                return self._file_bytes(html, "text/html; charset=utf-8")
            if u.path == "/api/diag":
                # one page that answers "did the email actually go out?" without a key
                from app.services import mailer as mailer_mod
                with dbmod.db() as conn:
                    rows = dbmod.rows(conn.execute(
                        "SELECT id, to_email, template, status, error, created_at"
                        " FROM emails ORDER BY id DESC LIMIT 12"))
                    counts = {r["status"]: r["n"] for r in dbmod.rows(conn.execute(
                        "SELECT status, COUNT(*) n FROM emails GROUP BY status"))}
                d = mailer_mod.diagnose()
                probe = ""
                if d["sender"] != "none":
                    try:
                        mailer_mod.send_now(d.get("fromEmail") or
                                            catalog()["shop"].get("email", ""),
                                            "Bimmer House Calls — send check",
                                            "<p>Send check from /api/diag.</p>")
                        probe = "send OK"
                    except Exception as exc:  # noqa: BLE001
                        probe = f"{type(exc).__name__}: {exc}"
                return self._json({"sender": d["sender"], "problem": d["problem"],
                                   "probe": probe, "counts": counts, "recent": rows})
            if u.path in ("/api/env-check",):
                # which BHC_ variables this process can actually see (names only)
                names = sorted(k for k in os.environ if k.startswith("BHC_"))
                return self._json({"count": len(names), "names": names,
                                   "pythonpath": os.environ.get("PYTHONPATH", ""),
                                   "cwd": os.getcwd()}, 200)
            if u.path in ("/api/email-status",):
                from app.services import mailer as mailer_mod
                d = mailer_mod.diagnose()
                return self._json(d, 200 if d["sender"] != "none" else 503)
            if u.path in ("/status", "/health", "/email-status"):
                from app.services import mailer as mailer_mod
                d = mailer_mod.diagnose()
                ok = d["sender"] != "none"
                rows = "".join(f"<tr><td>{k}</td><td><b>{v}</b></td></tr>" for k, v in d.items())
                html = ("<!doctype html><meta charset='utf-8'><title>Email status</title>"
                        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
                        "max-width:640px;margin:40px auto;padding:0 18px;color:#0B0B0D}"
                        "td{padding:6px 12px 6px 0;border-bottom:1px solid #e5e8ec;vertical-align:top}"
                        ".ok{background:#e7f7ee;color:#0a7d43;padding:10px 14px;border-radius:10px}"
                        ".bad{background:#fdecec;color:#b42318;padding:10px 14px;border-radius:10px}"
                        "code{background:#f6f8fa;padding:2px 5px;border-radius:4px}</style>"
                        f"<h2>Bimmer House Calls — email status</h2>"
                        f"<div class='{'ok' if ok else 'bad'}'>"
                        f"{'Email is configured and can send.' if ok else 'Email is NOT configured — nothing will send.'}"
                        "</div><table style='margin-top:18px'>" + rows + "</table>"
                        "<p style='color:#5b6470;font-size:13px;margin-top:20px'>"
                        "To fix: add <code>BHC_SMTP_USER</code> and <code>BHC_SMTP_PASS</code> "
                        "(a Gmail app password) in Render → Environment, then redeploy.</p>")
                return self._file_bytes(html, "text/html; charset=utf-8", 200 if ok else 503)
            if u.path in ("/admin", "/admin/"):
                return self._file(os.path.join(STATIC, "admin.html"))
            if u.path in ("/book", "/book-now", "/schedule", "/booking", "/booking/"):
                return self._file(os.path.join(STATIC, "index.html"))
            rel = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            safe = os.path.normpath(os.path.join(STATIC, rel))
            if not safe.startswith(STATIC):
                return self._json({"error": "forbidden"}, 403)
            return self._file(safe)
        except LookupError:
            return self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("ERROR GET %s: %r\n" % (self.path, exc))
            return self._json({"error": "not available"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid JSON"}, 400)
        try:
            if u.path.startswith("/api/run/"):
                return self._run_job()
            if u.path == "/api/quote":
                return self._json(do_quote(body))
            if u.path == "/api/request":
                return self._json(do_request(body), 201)
            m = re.fullmatch(r"/api/p/([\w\-]+)/sign", u.path)
            if m:
                ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0]
                return self._json(sign_proposal(m.group(1), body, ip, self.headers.get("User-Agent", "")))
            m = re.fullmatch(r"/api/p/([\w\-]+)/decline", u.path)
            if m:
                with dbmod.db() as conn:
                    conn.execute("UPDATE proposals SET status='declined' WHERE public_token=?", (m.group(1),))
                return self._json({"declined": True})
            if u.path.startswith("/api/admin/"):
                if not self._admin_ok():
                    return self._json({"error": "unauthorized"}, 401)
                return self._json(handle_admin(u.path.rsplit("/", 1)[-1], body))
            return self._json({"error": "not found"}, 404)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except KeyError as exc:
            return self._json({"error": str(exc)}, 404)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("ERROR %s %s: %r\n" % (self.command, self.path, exc))
            return self._json({"error": "Something went wrong on my end — please try again, "
                                        "or call (732) 890-8458"}, 500)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def serve(port: int = 8080):
    dbmod.init()
    with dbmod.db() as conn:
        terms.install_templates(conn, catalog())
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Bimmer House Calls API on http://localhost:{port}  (db: {dbmod.DB_PATH})")
    httpd.serve_forever()


if __name__ == "__main__":
    serve(int(os.environ.get("PORT", "8080")))
