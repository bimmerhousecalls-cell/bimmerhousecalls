"""Booking / quote / proposal / invoice engine.

The whole money path in one place:
  request -> lead -> quote (travel fee + lines) -> proposal (terms + e-sign)
          -> deposit invoice -> signed -> booking confirmed -> balance invoice
Every transition writes an audit row and queues the emails it owes.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import pricing


# ------------------------------------------------------------------ helpers

def now() -> datetime:
    return datetime.now()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


def _parse(s: str | None) -> datetime | None:
    """Never raise on a half-typed date: no date just means 'no slot yet'."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip())
    except (ValueError, TypeError):
        return None


def token(n: int = 24) -> str:
    return secrets.token_urlsafe(n)


def meta_set(conn, entity: str, entity_id: int, key: str, value) -> None:
    conn.execute("INSERT INTO meta(entity, entity_id, key, value) VALUES (?,?,?,?)"
                 " ON CONFLICT(entity, entity_id, key) DO UPDATE SET value=excluded.value",
                 (entity, entity_id, key, json.dumps(value)))


def meta_get(conn, entity: str, entity_id: int, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE entity=? AND entity_id=? AND key=?",
                       (entity, entity_id, key)).fetchone()
    return json.loads(row["value"]) if row and row["value"] is not None else default


def audit(conn, action: str, entity: str, entity_id: int, detail: str = "", actor: str = "system"):
    conn.execute("INSERT INTO audit(action, entity, entity_id, detail, actor) VALUES (?,?,?,?,?)",
                 (action, entity, entity_id, detail, actor))


def next_number(conn, table: str, prefix: str) -> str:
    year = now().year
    like = f"{prefix}-{year}-%"
    row = conn.execute(f"SELECT number FROM {table} WHERE number LIKE ? ORDER BY id DESC LIMIT 1",
                       (like,)).fetchone()
    seq = int(row["number"].split("-")[-1]) + 1 if row else 1001
    return f"{prefix}-{year}-{seq}"


def upsert_client(conn, **c) -> int:
    email = (c.get("email") or "").strip().lower() or None
    if email:
        row = conn.execute("SELECT id FROM clients WHERE lower(email)=?", (email,)).fetchone()
        if row:
            conn.execute(
                "UPDATE clients SET name=COALESCE(?,name), phone=COALESCE(?,phone), address=COALESCE(?,address),"
                " city=COALESCE(?,city), zip=COALESCE(?,zip), lat=COALESCE(?,lat), lng=COALESCE(?,lng),"
                " updated_at=datetime('now') WHERE id=?",
                (c.get("name"), c.get("phone"), c.get("address"), c.get("city"), c.get("zip"),
                 c.get("lat"), c.get("lng"), row["id"]))
            return row["id"]
    cur = conn.execute(
        "INSERT INTO clients(name, email, phone, address, city, state, zip, lat, lng, source, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (c.get("name") or "New client", email, c.get("phone"), c.get("address"), c.get("city"),
         c.get("state", "NJ"), c.get("zip"), c.get("lat"), c.get("lng"),
         c.get("source", "website"), c.get("notes")))
    return cur.lastrowid


def upsert_vehicle(conn, client_id: int, vin: str, **v) -> int:
    vin = vin.strip().upper()
    row = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
    if row:
        conn.execute("UPDATE vehicles SET client_id=?, model=COALESCE(?,model), engine=COALESCE(?,engine),"
                     " sunroof=COALESCE(?,sunroof) WHERE id=?",
                     (client_id, v.get("model"), v.get("engine"), v.get("sunroof"), row["id"]))
        return row["id"]
    decoded = pricing.vin_decode_stub(vin)
    cur = conn.execute(
        "INSERT INTO vehicles(client_id, vin, year, model, engine, sunroof, notes)"
        " VALUES (?,?,?,?,?,?,?)",
        (client_id, vin, decoded.get("year"), v.get("model"), v.get("engine"),
         v.get("sunroof"), v.get("notes")))
    return cur.lastrowid


# ------------------------------------------------------------------ quoting

def build_quote(catalog: dict, request: dict, when: datetime | None = None) -> dict:
    """Turn a website request into priced lines. request keys:
    items[], addons[], package, lat, lng, when, variant, discount{label,amount,percent}
    """
    lines = []
    variant = int(request.get("variant") or 0)
    start_dt = when or _parse(request.get("when"))
    ids = list(request.get("items") or [])
    if request.get("package"):
        ids.insert(0, request["package"])
    for item_id in ids:
        p = pricing.price_item(catalog, item_id, model_variant=variant)
        if p["needsQuote"]:
            lines.append({"id": p["id"], "name": p["name"], "qty": 1, "unit": 0,
                          "kind": "service", "needsQuote": True,
                          "note": "Quoted by VIN — to be confirmed before booking"})
        else:
            lines.append({"id": p["id"], "name": p["name"], "qty": 1, "unit": p["unitPrice"],
                          "kind": "service", "note": p["desc"]})
    for addon_id in request.get("addons") or []:
        p = pricing.price_item(catalog, addon_id)
        lines.append({"id": p["id"], "name": p["name"], "qty": 1,
                      "unit": p["unitPrice"] or 0, "kind": "addon",
                      "needsQuote": p["needsQuote"], "note": p["desc"]})

    travel = None
    if request.get("lat") is not None and request.get("lng") is not None:
        travel = pricing.travel_quote(catalog, float(request["lat"]), float(request["lng"]),
                                      when=start_dt)
        if travel["travelFee"]:
            lines.append({"id": "travel", "name": "Travel fee",
                          "qty": 1, "unit": travel["travelFee"], "kind": "travel",
                          "note": f"{travel['miles']} mi each way · {travel['driveMinutesOneWay']} min drive"
                                  + (f" · {travel['zone']}" if travel["zone"] else "")})

    custom = bool(request.get("custom") or request.get("customRequest"))
    if custom and not lines:
        # A custom build has no menu price yet: one TBD line the owner fills in.
        lines.append({"id": "custom-work", "name": "Custom work (quoted after review)", "qty": 1,
                      "unit": 0, "kind": "service", "needsQuote": True,
                      "note": (request.get("answers") or {}).get("custom", "") or "Build details to be confirmed"})

    disc = request.get("discount")
    if disc and (disc.get("amount") or disc.get("percent")):
        sub = sum(l["qty"] * l["unit"] for l in lines)
        amt = disc.get("amount") or round(sub * float(disc["percent"]) / 100, 2)
        lines.append({"id": "discount", "name": disc.get("label", "Discount"), "qty": 1,
                      "unit": -abs(float(amt)), "kind": "discount"})

    q = pricing.Quote(client={}, vehicle={}, scheduled_at=_iso(when),
                      taxRate=catalog["shop"]["taxRateNJ"],
                      depositPercent=catalog["shop"].get("depositPercent", 0))
    q.lines = [pricing.QuoteLine(l["id"], l["name"], l["qty"], l["unit"], l["kind"]) for l in lines]
    totals = q.totals(catalog["shop"].get("taxAppliesToLabor", False), custom=custom,
                      deposit_percent=catalog["shop"].get("depositPercentCustom", 25))
    totals["depositKind"] = "custom" if custom else "none"

    item_ids = [i for i in ids + list(request.get("addons") or [])]
    job_hours = pricing.labor_hours(catalog, item_ids) or 1
    slot = pricing.slot_for(catalog, item_ids, start_dt) if start_dt else None
    return {"lines": lines, "travel": travel, "totals": totals,
            "jobHours": job_hours, "slot": slot, "custom": custom,
            "questions": pricing.questions_for(catalog, [i for i in ids + list(request.get("addons") or [])
                                                          if not i.startswith("add-")],
                                                request.get("package"), custom),
            "depositPercent": catalog["shop"].get("depositPercentCustom", 25)}


def create_booking(conn, catalog: dict, payload: dict) -> dict:
    """Website request in, booking + quote + proposal out."""
    client_id = upsert_client(conn, **payload.get("client", {}))
    veh = dict(payload.get("vehicle") or {})
    vin = veh.pop("vin", "")
    vehicle_id = upsert_vehicle(conn, client_id, vin, **veh)
    when = _parse(payload.get("when"))
    # a random 4-digit code collides once the table is busy, so keep drawing
    # until it is free instead of failing the request
    code = ""
    for _ in range(40):
        cand = f"BHC-{now().year}-{secrets.randbelow(9000) + 1000}"
        if not conn.execute("SELECT 1 FROM bookings WHERE code=?", (cand,)).fetchone():
            code = cand
            break
    if not code:
        code = f"BHC-{now().year}-{secrets.randbelow(900000) + 100000}"
    quote = build_quote(catalog, payload, when)
    cur = conn.execute(
        "INSERT INTO bookings(code, client_id, vehicle_id, status, scheduled_start, scheduled_end,"
        " travel_miles, travel_fee, travel_json, job_hours, request_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (code, client_id, vehicle_id, "quoted",
         quote["slot"]["start"] if quote["slot"] else None,
         quote["slot"]["end"] if quote["slot"] else None,
         (quote["travel"] or {}).get("miles"),
         (quote["travel"] or {}).get("travelFee", 0),
         json.dumps(quote["travel"] or {}),
         quote["jobHours"],
         json.dumps(payload)))
    booking_id = cur.lastrowid
    answers = payload.get("answers") or {}
    meta_set(conn, "booking", booking_id, "answers", answers)
    meta_set(conn, "booking", booking_id, "questions", quote["questions"])
    meta_set(conn, "booking", booking_id, "custom", quote["custom"])
    proposal = create_proposal(conn, booking_id, quote)
    audit(conn, "booking.created", "booking", booking_id, code)
    return {"bookingId": booking_id, "code": code, "clientId": client_id,
            "vehicleId": vehicle_id, "proposal": proposal, "quote": quote}


def create_proposal(conn, booking_id: int, quote: dict, terms: dict | None = None) -> dict:
    number = next_number(conn, "proposals", "P")
    p_token = token()
    expires = (now() + timedelta(days=14)).isoformat(timespec="minutes")
    cur = conn.execute(
        "INSERT INTO proposals(booking_id, number, status, lines_json, totals_json,"
        " terms_version, terms_hash, public_token, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (booking_id, number, "draft", json.dumps(quote["lines"]), json.dumps(quote["totals"]),
         (terms or {}).get("version"), (terms or {}).get("sha256"), p_token, expires))
    audit(conn, "proposal.created", "proposal", cur.lastrowid, number)
    return {"proposalId": cur.lastrowid, "number": number, "publicToken": p_token,
            "expiresAt": expires, "totals": quote["totals"], "lines": quote["lines"]}


def sign_proposal(conn, proposal_id: int, signature: dict) -> dict:
    """E-signature capture. Records name, drawn image, IP, UA, and a hash of the
    exact document that was signed so the agreement can be proven later."""
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise KeyError("proposal not found")
    if row["status"] in ("signed",):
        return dict(row)
    doc = {
        "proposal": row["number"],
        "lines": json.loads(row["lines_json"]),
        "totals": json.loads(row["totals_json"]),
        "termsVersion": row["terms_version"],
        "termsHash": row["terms_hash"],
        "signedBy": signature.get("name"),
        "signedAt": now().isoformat(timespec="seconds"),
        "acknowledged": signature.get("acknowledged"),
    }
    signed_hash = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    conn.execute(
        "UPDATE proposals SET status='signed', signed_at=?, signature_name=?, signature_image=?,"
        " signature_ip=?, signature_ua=?, signed_hash=? WHERE id=?",
        (doc["signedAt"], signature.get("name"), signature.get("image"),
         signature.get("ip"), signature.get("ua"), signed_hash, proposal_id))
    conn.execute("UPDATE bookings SET status='signed', updated_at=datetime('now') WHERE id=?",
                 (row["booking_id"],))
    audit(conn, "proposal.signed", "proposal", proposal_id, signed_hash)
    return {"signedHash": signed_hash, "signedAt": doc["signedAt"]}


def create_invoice(conn, booking_id: int, proposal_id: int | None, kind: str = "deposit") -> dict:
    row = conn.execute("SELECT totals_json, number FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    totals = json.loads(row["totals_json"]) if row else {}
    number = next_number(conn, "invoices", "INV")
    inv_token = token()
    amount = totals.get("deposit" if kind == "deposit" else "balance", totals.get("total", 0))
    if kind == "deposit" and not amount:
        # Standard menu jobs take no deposit — the balance invoice is the whole job.
        kind = "balance"
        amount = totals.get("balance") or totals.get("total", 0)
    body = {**totals, "amountDue": amount, "kind": kind}
    cur = conn.execute(
        "INSERT INTO invoices(booking_id, proposal_id, number, status, totals_json, due_at, public_token)"
        " VALUES (?,?,?,?,?,?,?)",
        (booking_id, proposal_id, number, "draft", json.dumps(body),
         (now() + timedelta(days=7)).isoformat(timespec="minutes"), inv_token))
    audit(conn, f"invoice.{kind}.created", "invoice", cur.lastrowid, number)
    return {"invoiceId": cur.lastrowid, "number": number, "amountDue": amount, "publicToken": inv_token}


def create_manual_invoice(conn, booking_id: int, amount: float, kind: str = "payment",
                          description: str | None = None, due_days: int = 7) -> dict:
    """Owner-made invoice for any amount — a change order, parts, a trip charge."""
    number = next_number(conn, "invoices", "INV")
    inv_token = token()
    totals = {"amountDue": round(float(amount), 2), "kind": kind,
              "description": description or "Service", "deposit": 0, "balance": round(float(amount), 2)}
    cur = conn.execute(
        "INSERT INTO invoices(booking_id, number, status, totals_json, due_at, public_token)"
        " VALUES (?,?,?,?,?,?)",
        (booking_id, number, "draft", json.dumps(totals),
         (now() + timedelta(days=due_days)).isoformat(timespec="minutes"), inv_token))
    audit(conn, "invoice.manual.created", "invoice", cur.lastrowid, number, "owner")
    return {"invoiceId": cur.lastrowid, "number": number, "amountDue": totals["amountDue"],
            "publicToken": inv_token, "link": f"/i/{inv_token}"}


def catalog_shop_parts_excluded() -> bool:
    """True when the shop's prices are labor only (customer supplies the parts)."""
    try:
        shop = pricing.load_catalog()["shop"]
        return not shop.get("partsIncluded", False)
    except Exception:  # noqa: BLE001
        return False


def update_invoice(conn, invoice_id: int, lines: list[dict] | None = None,
                   note: str = "", tax_rate: float | None = None,
                   notes: str | None = None) -> dict:
    """Edit an invoice before it is paid: change quantities, prices, add or drop lines.

    The proposal's estimate is only the starting point — the owner's final invoice is
    what counts. Every edit is written to the audit log, and once money is recorded
    the invoice can no longer be edited (issue a new one instead).
    """
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        raise KeyError("invoice not found")
    body = json.loads(inv["totals_json"] or "{}")
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?",
                        (invoice_id,)).fetchone()["s"]
    if paid > 0:
        raise ValueError("This invoice already has a payment on it — issue a new invoice instead of editing")
    clean = []
    for l in (lines or []):
        qty = float(l.get("qty", 1) or 1)
        unit = float(l.get("unit", 0) or 0)
        clean.append({"name": (l.get("name") or "Item").strip(), "qty": qty, "unit": round(unit, 2),
                      "total": round(qty * unit, 2), "kind": l.get("kind", "service")})
    if not clean:
        raise ValueError("An invoice needs at least one line")
    subtotal = round(sum(l["total"] for l in clean), 2)
    rate = float(tax_rate if tax_rate is not None else body.get("taxRate", 0) or 0)
    # the client supplies the parts, so the owner's prices are labor — no NJ tax
    if catalog_shop_parts_excluded():
        rate = 0.0
    tax = round(subtotal * rate, 2)
    total = round(subtotal + tax, 2)
    # the owner may add a notes block: anything they want the client to read
    if notes is not None:
        body["notes"] = (notes or "").strip()
    body.update({"lines": clean, "subtotal": subtotal, "taxRate": rate, "tax": tax,
                 "total": total, "amountDue": total, "balance": total,
                 "note": note or body.get("note", ""), "editedBy": "owner",
                 "editedAt": now().isoformat(timespec="seconds")})
    # editing never changes whether it has been sent — only "Send invoice" does that
    conn.execute("UPDATE invoices SET totals_json=? WHERE id=?",
                 (json.dumps(body), invoice_id))
    audit(conn, "invoice.edited", "invoice", invoice_id, json.dumps(clean)[:400])
    return {"invoiceId": invoice_id, "number": inv["number"], "subtotal": subtotal,
            "tax": tax, "total": total, "amountDue": total, "lines": clean,
            "status": inv["status"], "notes": body.get("notes", "")}


def record_payment(conn, invoice_id: int, amount: float, method: str = "card",
                   processor: str = "manual", ref: str | None = None, note: str = "") -> dict:
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    body = json.loads(inv["totals_json"])
    conn.execute("INSERT INTO payments(invoice_id, amount, kind, method, processor, processor_ref, note)"
                 " VALUES (?,?,?,?,?,?,?)",
                 (invoice_id, amount, body.get("kind", "payment"), method, processor, ref, note))
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?",
                        (invoice_id,)).fetchone()["s"]
    status = "paid" if paid >= body.get("amountDue", 0) - 0.01 else ("partial" if paid > 0 else "open")
    conn.execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
    if body.get("kind") == "deposit" and status == "paid":
        conn.execute("UPDATE bookings SET status='deposit_paid', updated_at=datetime('now') WHERE id=?",
                     (inv["booking_id"],))
    audit(conn, "payment.recorded", "invoice", invoice_id, f"{amount} {method}")
    return {"invoiceStatus": status, "paid": paid, "balance": round(body.get("amountDue", 0) - paid, 2)}


if __name__ == "__main__":
    dbmod.init()
    cat = pricing.load_catalog()
    with dbmod.db() as conn:
        out = create_booking(conn, cat, {
            "client": {"name": "Sarah Johnson", "email": "sarah@example.com",
                       "phone": "7325551234", "address": "12 Ocean Ave", "city": "Point Pleasant",
                       "zip": "08742", "lat": 40.0832, "lng": -74.0682},
            "vehicle": {"vin": "WBA3A5C55CF256789", "model": "335i"},
            "items": ["oil-service", "brake-pads-rotors"],
            "addons": ["add-cabin-filter"],
            "when": (now() + timedelta(days=3)).replace(hour=10, minute=0).isoformat(timespec="minutes"),
        })
        print(json.dumps(out["quote"]["totals"], indent=2))
        print("booking", out["code"], "proposal", out["proposal"]["number"])

def reset_demo_data(conn, keep_settings: bool = True) -> dict:
    """Wipe test clients, bookings, quotes, invoices and email queue.

    Keeps the catalog, templates, theme and the admin key, so the site comes
    back empty but configured — ready for the first real customer.
    """
    counts = {}
    conn.execute("PRAGMA foreign_keys = OFF")
    for tbl in ("payments", "invoices", "proposals", "bookings", "vehicles", "clients", "emails", "audit"):
        n = conn.execute(f"SELECT COUNT(*) c FROM {tbl}").fetchone()["c"]
        counts[tbl] = n
        conn.execute(f"DELETE FROM {tbl}")
    if not keep_settings:
        counts["meta"] = conn.execute("SELECT COUNT(*) c FROM meta").fetchone()["c"]
        conn.execute("DELETE FROM meta")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
                 "('payments','invoices','proposals','bookings','vehicles','clients','emails')")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    return counts
