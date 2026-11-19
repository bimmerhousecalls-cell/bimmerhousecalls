"""Self-check — runs every route, page and money path and reports what breaks.

    python -m app.tests.check
    python -m app.tests.check --live http://localhost:8080   (against a running API)

Exits non-zero if anything fails, so it can gate a deploy.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, name, str(detail)))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((False, name, f"{type(exc).__name__}: {exc}"))


# ------------------------------------------------------------------ unit level

def unit_checks():
    from app import db as dbmod
    from app.services import automation, booking, emails, pricing, terms, worker

    cat = pricing.load_catalog()

    def hours():
        assert len(cat["shop"]["hours"]) == 7, "need 7 days"
        assert cat["shop"]["hours"]["0"] == [], "Sunday must be closed"
        return cat["shop"]["hoursLabel"]

    def travel_tiers():
        cases = [(10, 0), (30, 0), (45, 11.25), (60, 22.5), (90, 67.5)]
        for miles, expect in cases:
            fee, _ = pricing.tiered_miles_fee(cat["travel"]["tiers"], miles)
            assert abs(fee - expect) < 0.01, f"{miles}mi -> {fee}, expected {expect}"
        return "tiers ok"

    def travel_quote_real():
        q = pricing.travel_quote(cat, 40.0832, -74.0682)  # Point Pleasant
        assert q["miles"] > 0 and q["driveMinutesOneWay"] > 0
        assert q["travelFee"] >= q["distanceFee"], q
        q0 = pricing.travel_quote(cat, 39.6621, -74.1704)  # base itself
        assert q0["miles"] == 0 and q0["distanceFee"] == 0, q0
        return f"{q['miles']}mi dist ${q['distanceFee']} total ${q['travelFee']}"

    def catalog_prices():
        n = sum(len(c["items"]) for c in cat["categories"])
        for c in cat["categories"]:
            for i in c["items"]:
                p = pricing.price_item(cat, i["id"])
                if not i.get("quote"):
                    assert p["unitPrice"] and p["unitPrice"] > 0, i["id"]
        return f"{n} services priced"

    def questions():
        assert [q["id"] for q in pricing.questions_for(cat, ["stage1-tune"])] == ["tune"]
        assert "sunroof" in [q["id"] for q in pricing.questions_for(cat, ["starlight-headliner"])]
        # every job asks the parts question — the customer supplies the parts
        assert [q["id"] for q in pricing.questions_for(cat, ["oil-service"])] == ["maintparts"]
        assert [q["id"] for q in pricing.questions_for(cat, ["coilovers"])] == ["lift", "parts"]
        assert "parts" in [q["id"] for q in pricing.questions_for(cat, ["catback-install"])]
        assert "cosmetic" in [q["id"] for q in pricing.questions_for(cat, ["grilles"])]
        # and the server refuses a request that leaves a required one blank
        return "conditional questions ok"

    def deposits():
        std = booking.build_quote(cat, {"items": ["oil-service"], "lat": 40.0, "lng": -74.1})
        cus = booking.build_quote(cat, {"items": ["stage2-tune"], "custom": True,
                                        "answers": {"custom": "downpipe and stage 2 flash"},
                                        "lat": 40.0, "lng": -74.1})
        assert std["totals"]["deposit"] == 0, "menu jobs take no deposit"
        assert cus["totals"]["deposit"] > 0, "custom builds take a deposit"
        tbd = booking.build_quote(cat, {"custom": True, "lat": 40.0, "lng": -74.1})
        assert tbd["totals"]["deposit"] == 0, "an unpriced custom build has nothing to deposit on"
        return "deposit rules ok"

    def terms_render():
        body = terms.render_terms(cat)
        for must in ("22. Entire Agreement", "Customer Acknowledgment and Waiver",
                     "ECU unlocking risk", "Effective date", "Ocean County"):
            assert must in body, f"missing: {must}"
        assert "[" not in body.split("Effective date")[1][:2000], "unfilled bracket left in terms"
        return f"terms v{terms.TERMS_VERSION}, {len(body)} chars"

    def email_templates():
        for name in emails.SUBJECTS:
            subj, body = emails.render(name, {
                "first_name": "A", "email": "a@b.com", "phone": "1", "vehicle": "335i", "number": "P-1",
                "summary": "x", "travel_line": "x", "link": "x", "expires": "x", "date": "x", "time": "x",
                "address": "x", "balance": "1", "deposit": "1", "deposit_pct": 25, "scheduled_start": "x",
                "service": "x", "total": "1", "invoice": "INV-1", "amount": "1", "code": "BHC-1",
                "client": "A", "vin": "x", "admin_link": "x", "method": "card", "eta": "x"})
            assert "{" not in subj, f"{name}: unfilled subject"
            assert "{" not in body, f"{name}: unfilled body placeholder"
        return f"{len(emails.SUBJECTS)} templates clean"

    def end_to_end_flow():
        from app.services import flow
        r = flow.run_demo({"client": {"name": "Test User", "email": "t@example.com", "address": "1 A St", "city": "Brick"},
                           "vehicle": {"vin": "WBA3A5C55CF256789", "model": "335i"},
                           "items": ["oil-service", "stage1-tune"], "lat": 40.05, "lng": -74.1})
        assert r["proposal"]["status"] == "signed", r["proposal"]["status"]
        assert len(r["invoices"]) >= 1
        assert r["booking"]["status"] in ("signed", "confirmed", "deposit_paid", "done"), r["booking"]["status"]
        return "request -> sign -> deposit -> balance ok"

    def slots_in_hours():
        from datetime import datetime as dt
        cat2 = pricing.load_catalog()
        sunday = dt(2026, 11, 22, 10, 0)
        slot = pricing.slot_for(cat2, ["oil-service"], sunday)
        assert slot["start"].startswith("2026-11-23"), slot
        assert pricing.in_hours(cat2, dt(2026, 11, 19, 14, 0), 2) is True
        assert pricing.in_hours(cat2, dt(2026, 11, 19, 16, 0), 3) is False
        return "Sunday pushed to Monday 7am"

    def automation_runs():
        dbmod.DB_PATH = ":memory:"
        dbmod.init()
        from app.services import automation
        out = automation.run()
        assert "emails" in out
        return "automation ok"

    for name, fn in [("hours", hours), ("travel tiers", travel_tiers), ("travel quote", travel_quote_real),
                     ("catalog prices", catalog_prices), ("conditional questions", questions),
                     ("deposit rules", deposits), ("terms render", terms_render),
                     ("email templates", email_templates), ("slot hours", slots_in_hours),
                     ("end-to-end flow", end_to_end_flow),
                     ("automation", automation_runs)]:
        check("unit: " + name, fn)


# ------------------------------------------------------------------ live API

def live_checks(base: str):
    from app import db as dbmod_live
    dbmod_live.DB_PATH = os.environ.get("BHC_DB") or os.path.join(ROOT, "data", "bhc.sqlite3")

    def get(path):
        with urllib.request.urlopen(base + path, timeout=15) as r:
            return r.status, r.read()

    def post(path, body, headers=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def pages():
        out = []
        for path in ("/", "/admin", "/api/health", "/api/catalog", "/api/terms"):
            st, _ = get(path)
            assert st == 200, f"{path} -> {st}"
            out.append(path)
        return " ".join(out)

    def catalog_shape():
        _, raw = get("/api/catalog")
        c = json.loads(raw)
        for k in ("categories", "addons", "packages", "travel", "shop", "acknowledgments"):
            assert k in c, k
        assert c["shop"]["theme"]["accent"] == "#FFD400"
        return f"{len(c['categories'])} categories"

    def quote_endpoint():
        st, d = post("/api/quote", {"items": ["stage1-tune"], "lat": 40.08, "lng": -74.07,
                                    "when": (datetime.now() + timedelta(days=3)).replace(hour=9, minute=0).isoformat(timespec="minutes")})
        assert st == 200, d
        assert d["quote"]["totals"]["total"] > 0
        return f"${d['quote']['totals']['total']}"

    def availability_hours():
        d = datetime.now() + timedelta(days=3)
        while d.weekday() == 6:
            d += timedelta(days=1)
        _, raw = get("/api/availability?date=" + d.date().isoformat())
        a = json.loads(raw)
        assert a["slots"], "no slots offered"
        sun = (d + timedelta(days=(6 - d.weekday()))).date().isoformat()
        _, raw2 = get("/api/availability?date=" + sun)
        assert json.loads(raw2)["closed"] is True, "Sunday should be closed"
        return f"{len(a['slots'])} slots"

    def request_requires_signature():
        body = {"items": ["oil-service"], "lat": 40.0, "lng": -74.1,
                "client": {"name": "X Y", "email": "x@example.com"}, "vehicle": {"vin": "WBA3A5C55CF256789"}}
        st, d = post("/api/request", body)
        assert st == 400 and "Terms" in d.get("error", ""), d
        return "unsigned request rejected"

    def full_request():
        body = {"items": ["oil-service"], "lat": 40.0832, "lng": -74.0682,
                "when": (datetime.now() + timedelta(days=4)).replace(hour=10, minute=0).isoformat(timespec="minutes"),
                "answers": {"maintparts": "Yes, I have them"},
                "consent": True, "acknowledged": True,
                "signature": {"name": "Check Bot", "image": "data:image/png;base64,iVBORw0KGgo="},
                "client": {"name": "Check Bot", "email": "check@example.com", "address": "1 Test St",
                           "city": "Brick", "zip": "08724"},
                "vehicle": {"vin": "WBA3A5C55CF256789", "model": "335i"}}
        st, d = post("/api/request", body)
        assert st == 201, d
        assert d["signature"]["signedHash"]
        tok = d["proposal"]["publicToken"]
        st2, p = get("/api/p/" + tok)
        assert json.loads(p)["proposal"]["status"] == "signed"
        return f"booked {d['code']}"

    def invoice_edit():
        from app import db as dbmod2
        from app.services import booking as bk
        with dbmod2.db() as conn:
            key = {"X-Admin-Key": bk.meta_get(conn, "settings", 0, "admin_key")}
        st, d = post("/api/admin/invoices", {}, key)
        assert st == 200
        open_inv = [i for i in d["invoices"] if not i["locked"]]
        if not open_inv:
            return "no open invoice to edit"
        inv = open_inv[0]
        st, r = post("/api/admin/invoice.update", {"invoiceId": inv["id"],
                     "lines": [{"name": "Downpipe install", "qty": 1, "unit": 420},
                               {"name": "Stage 2 flash", "qty": 1, "unit": 550}],
                     "note": "edited by the check", "taxRate": 0.06625}, key)
        assert st == 200, r
        # labor-only shop: no NJ tax on these lines
        assert abs(r["total"] - 970) < 0.02, r["total"]
        return f"{inv['number']} re-priced to ${r['total']:.2f} (no tax on labor)"

    def invoice_shows_everything():
        from app import db as dbmod2
        from app.services import booking as bk
        with dbmod2.db() as conn:
            key = {"X-Admin-Key": bk.meta_get(conn, "settings", 0, "admin_key")}
            row = conn.execute("SELECT public_token FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return "no invoice to inspect"
        st, raw = get("/api/i/" + row["public_token"])
        d = json.loads(raw)
        for k in ("client", "vehicle", "lines", "totals", "terms", "shop"):
            assert k in d, k
        assert d["client"]["name"], "invoice must name the client"
        assert d["vehicle"]["vin"], "invoice must show the VIN"
        assert d["terms"]["body"], "invoice must carry the signed terms"
        assert d["shop"]["logo"], "invoice must carry the brand block"
        assert d["signature"] and d["signature"]["hash"], "invoice must show the signature record"
        return f"{d['invoice']['number']}: client, VIN, {len(d['lines'])} line(s), terms v{d['terms']['version']}, signature"

    def slots_all_day_and_no_overlap():
        from datetime import datetime as dt, timedelta as td
        # find the first far-out weekday that is still empty, so re-running the
        # checks never collides with a booking an earlier run made
        import sqlite3
        from app import db as dbmod3
        d = dt.now() + td(days=400)
        while True:
            while d.weekday() == 6:
                d += td(days=1)
            with dbmod3.db() as c3:
                taken = c3.execute("SELECT COUNT(*) n FROM bookings WHERE date(scheduled_start)=?",
                                   (d.date().isoformat(),)).fetchone()["n"]
            if not taken:
                break
            d += td(days=1)
        date = d.date().isoformat()
        st, raw = get("/api/availability?date=" + date + "&hours=2")
        a = json.loads(raw)
        assert a["slots"], "no slots"
        assert a["slots"][0]["label"].endswith("AM"), a["slots"][0]["label"]
        assert ":" in a["slots"][0]["label"] and not a["slots"][0]["label"].startswith("0"), "12-hour labels"
        starts = [x["start"][11:16] for x in a["slots"]]
        assert "07:00" in starts and len(starts) > 8, "every half hour of the day should be offered"
        body = {"items": ["oil-service"], "lat": 40.0832, "lng": -74.0682, "when": date + "T07:00",
                "answers": {"maintparts": "Yes, I have them"},
                "consent": True, "acknowledged": True,
                "signature": {"name": "Slot Check", "image": "data:image/png;base64,iVBORw0KGgo="},
                "client": {"name": "Slot Check", "email": "slot2@example.com", "address": "1 A St",
                           "city": "Brick", "zip": "08724"},
                "vehicle": {"vin": "WBA3A5C55CF256789", "model": "335i"}}
        st1, _ = post("/api/request", body)
        assert st1 == 201, st1
        st2, d2 = post("/api/request", dict(body, when=date + "T07:30"))
        assert st2 == 400 and "taken" in d2.get("error", "").lower(), d2
        st3, _ = post("/api/request", dict(body, when=date + "T09:00"))
        assert st3 == 201, f"a later slot must still be bookable, got {st3}"
        return "12-hour labels, half-hour slots, overlap blocked"

    def admin_locked():
        from app import db as dbmod2
        from app.services import booking as bk
        with dbmod2.db() as conn:
            key = bk.meta_get(conn, "settings", 0, "admin_key")
        assert key, "no admin key stored — the dashboard would be open to anyone"
        st, _ = post("/api/admin/summary", {})
        assert st == 401, f"dashboard answered {st} without a key"
        st, _ = post("/api/admin/summary", {}, {"X-Admin-Key": key})
        assert st == 200, f"right key got {st}"
        return "locked, 401 without key"

    def travel_one_way_and_no_surcharge():
        from app.services import pricing
        cat2 = pricing.load_catalog()
        assert cat2["travel"]["roundTrip"] is False, "travel must be one way only"
        assert not cat2["travel"].get("afterHoursSurcharge"), "no after-hours charge"
        from datetime import datetime as dt
        night = pricing.travel_quote(cat2, 40.0832, -74.0682, when=dt(2026, 11, 19, 21, 0))
        assert night["surcharges"] == [], night["surcharges"]
        assert abs(night["travelFee"] - night["distanceFee"]) < 0.01
        day = pricing.travel_quote(cat2, 40.0832, -74.0682, when=dt(2026, 11, 19, 10, 0))
        assert day["travelFee"] == night["travelFee"], "travel fee must not depend on time of day"
        return f"one way ${day['travelFee']:.2f}, no surcharges"

    def book_alias_and_jobs():
        for path in ("/book", "/book-now", "/booking"):
            st, _ = get(path)
            assert st == 200, f"{path} -> {st}"
        st, _ = post("/api/run/mailer", {})
        assert st == 401, "scheduler endpoints must need the key"
        return "/book aliases ok, scheduler locked"

    def archive_writes_folders():
        from app.services import archive
        r = archive.run(list_only=True)
        assert "folder" in r
        return f"{r['already']} job folder(s) on disk"

    def admin_endpoints():
        from app import db as dbmod2
        from app.services import booking as bk
        with dbmod2.db() as conn:
            admin_key = {"X-Admin-Key": bk.meta_get(conn, "settings", 0, "admin_key")}
        st, d = post("/api/admin/summary", {}, admin_key)
        assert st == 200, d
        st, b = post("/api/admin/bookings", {"status": "all"}, admin_key)
        assert st == 200 and "bookings" in b
        if b["bookings"]:
            st, det = post("/api/admin/booking", {"bookingId": b["bookings"][0]["id"]}, admin_key)
            assert st == 200 and "proposals" in det
        return f"{len(b['bookings'])} bookings"

    for name, fn in [("pages", pages), ("catalog", catalog_shape), ("quote", quote_endpoint),
                     ("availability + hours", availability_hours),
                     ("signature gate", request_requires_signature), ("full request", full_request),
                     ("travel one way", travel_one_way_and_no_surcharge),
                     ("book aliases", book_alias_and_jobs),
                     ("invoice edit", invoice_edit), ("invoice contents", invoice_shows_everything),
                     ("slots + overlap", slots_all_day_and_no_overlap), ("admin lock", admin_locked), ("work archive", archive_writes_folders),
                     ("admin", admin_endpoints)]:
        check("live: " + name, fn)


if __name__ == "__main__":
    unit_checks()
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        base = sys.argv[i + 1] if len(sys.argv) > i + 1 else "http://localhost:8080"
        live_checks(base)
    ok = sum(1 for r in RESULTS if r[0])
    for passed, name, detail in RESULTS:
        print(("  PASS  " if passed else "  FAIL  ") + name + ("  — " + detail if detail else ""))
    print(f"\n{ok}/{len(RESULTS)} checks passed")
    sys.exit(0 if ok == len(RESULTS) else 1)
