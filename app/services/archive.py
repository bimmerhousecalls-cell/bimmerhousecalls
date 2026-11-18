"""Work archive — a folder per finished job, so nothing is only in a dashboard.

    python -m app.services.archive          # file every job that is done or paid
    python -m app.services.archive --list   # what's already filed

Each finished job becomes:

    work/2026-11/BHC-2026-4359_Chris-Lang/
        job.txt              everything at a glance (client, car, VIN, when, money)
        invoice-INV-2026-1001.txt
        signature-P-2026-1008.txt   name, time, IP, terms version, document hash
        emails.txt           every message we sent about this job

Files are written once and never overwritten, so the folder is a record, not a
working copy. Re-running only files jobs that aren't there yet.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "work")


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-")[:60] or "job"


def _money(v) -> str:
    return f"${float(v or 0):,.2f}"


def file_job(conn, booking_row) -> str:
    b = booking_row
    when = (b["scheduled_start"] or b["created_at"] or "")[:10]
    folder = os.path.join(WORK, when[:7], f"{b['code']}_{_safe(b['client'])}")
    if os.path.exists(os.path.join(folder, "job.txt")):
        return folder
    os.makedirs(folder, exist_ok=True)
    totals = json.loads(b["totals_json"] or "{}")
    travel = json.loads(b["travel_json"] or "{}") if b.get("travel_json") else {}
    lines = [
        f"Job {b['code']}",
        "=" * 60,
        f"Client:    {b['client']}",
        f"Phone:     {b.get('phone') or ''}",
        f"Email:     {b.get('email') or ''}",
        f"Address:   {b.get('address') or ''}",
        f"Vehicle:   {b.get('model') or 'BMW'}   VIN {b.get('vin') or ''}",
        f"Scheduled: {(b['scheduled_start'] or '').replace('T', ' ')}",
        f"Status:    {b['status']}",
        "",
        "Services",
        "-" * 60,
    ]
    for l in json.loads(b["lines_json"] or "[]"):
        lines.append(f"  {l.get('name')}  {_money(l.get('unit'))}")
    lines += ["", f"Total     {_money(totals.get('total'))}",
              f"Travel    {_money(travel.get('travelFee'))}  ({travel.get('miles', 0)} mi each way)",
              f"Drive     {travel.get('driveMinutesOneWay', 0)} min each way", ""]
    with open(os.path.join(folder, "job.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    for inv in dbmod.rows(conn.execute("SELECT * FROM invoices WHERE booking_id=?", (b["id"],))):
        t = json.loads(inv["totals_json"] or "{}")
        with open(os.path.join(folder, f"invoice-{_safe(inv['number'])}.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"Invoice {inv['number']}\nStatus: {inv['status']}\n"
                     f"Due: {_money(t.get('amountDue'))}\nTotal: {_money(t.get('total'))}\n"
                     f"Kind: {t.get('kind')}\nIssued: {inv['created_at']}\n")

    for p in dbmod.rows(conn.execute("SELECT * FROM proposals WHERE booking_id=?", (b["id"],))):
        with open(os.path.join(folder, f"signature-{_safe(p['number'])}.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"Proposal {p['number']}\nStatus: {p['status']}\n"
                     f"Signed by: {p['signature_name'] or ''}\nSigned at: {p['signed_at'] or ''}\n"
                     f"IP: {p['signature_ip'] or ''}\nDevice: {p['signature_ua'] or ''}\n"
                     f"Terms version: {p['terms_version'] or ''}\n"
                     f"Document hash: {p['signed_hash'] or ''}\n")

    mails = dbmod.rows(conn.execute(
        "SELECT to_email, subject, status, created_at FROM emails WHERE booking_id=? ORDER BY id", (b["id"],)))
    with open(os.path.join(folder, "emails.txt"), "w", encoding="utf-8") as fh:
        for m in mails:
            fh.write(f"{m['created_at']}  [{m['status']}]  {m['to_email']}  {m['subject']}\n")
    return folder


def run(list_only: bool = False) -> dict:
    dbmod.init()
    filed, skipped = [], 0
    with dbmod.db() as conn:
        rows = dbmod.rows(conn.execute("""
            SELECT b.*, c.name AS client, c.phone, c.email, c.address,
                   v.model, v.vin,
                   (SELECT lines_json FROM proposals p WHERE p.booking_id=b.id ORDER BY p.id DESC LIMIT 1) AS lines_json,
                   (SELECT totals_json FROM proposals p WHERE p.booking_id=b.id ORDER BY p.id DESC LIMIT 1) AS totals_json,
                   b.travel_json AS travel_json
            FROM bookings b
            JOIN clients c ON c.id=b.client_id
            LEFT JOIN vehicles v ON v.id=b.vehicle_id
            WHERE b.status IN ('done','paid','completed','confirmed','deposit_paid')
            ORDER BY b.scheduled_start"""))
        for r in rows:
            when = (r["scheduled_start"] or "")[:10]
            path = os.path.join(WORK, when[:7], f"{r['code']}_{_safe(r['client'])}")
            if os.path.exists(os.path.join(path, "job.txt")):
                skipped += 1
                continue
            if not list_only:
                filed.append(file_job(conn, r))
    return {"filed": len(filed), "already": skipped, "folder": WORK,
            "paths": filed[:20]}


if __name__ == "__main__":
    print(json.dumps(run(list_only="--list" in sys.argv), indent=2))
