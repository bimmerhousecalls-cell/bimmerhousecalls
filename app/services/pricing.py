"""Pricing engine: travel fees, drive time, quotes, invoices, deposits.

Pure functions over the catalog in data/services.json — no database, no network.
Everything money-related the site and the admin show goes through here so the
number on the proposal, the invoice and the PDF can never disagree.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOG_PATH = os.path.join(_HERE, "data", "services.json")


def load_catalog(path: str = CATALOG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- geo / travel

def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def road_miles(straight_miles: float, road_factor: float = 1.25) -> float:
    """Straight-line distance under-reports driving distance; NJ roads run ~1.25x."""
    return round(straight_miles * road_factor, 1)


def tiered_miles_fee(tiers: list, miles: float) -> tuple[float, list]:
    """Marginal tiers: each band is billed at its own rate.

    0-30 mi free, 30-60 mi at $0.75/mi, 60 mi+ at $1.50/mi — a 45 mile trip pays
    for 15 miles, a 70 mile trip pays 30 at .75 + 10 at 1.50.
    """
    fee = 0.0
    breakdown = []
    prev = 0.0
    for t in sorted(tiers, key=lambda x: (x["upToMiles"] is None, x["upToMiles"] or 0)):
        cap = t["upToMiles"]
        if cap is None:
            band = max(0.0, miles - prev)
        else:
            band = max(0.0, min(miles, cap) - prev)
        if band > 0 and t["perMile"]:
            amount = round(band * t["perMile"], 2)
            fee += amount
            breakdown.append({"from": prev, "to": prev + band, "miles": round(band, 1),
                              "perMile": t["perMile"], "amount": amount})
        prev = cap if cap is not None else prev
        if cap is not None and miles <= cap:
            break
    return round(fee, 2), breakdown


def zone_for_miles(catalog: dict, miles: float) -> dict | None:
    for zone in sorted(catalog["travel"].get("zones") or [], key=lambda z: z["maxMiles"]):
        if miles <= zone["maxMiles"]:
            return zone
    return None


def travel_quote(catalog: dict, lat: float, lng: float, when: datetime | None = None,
                 round_trip: bool | None = None) -> dict:
    """Travel fee + driving time for one job site, measured from the shop base.

    Returns the exact numbers the client sees before they book, plus the
    breakdown so the owner can justify every line.
    """
    t = catalog["travel"]
    shop = catalog["shop"]
    straight = haversine_miles(shop["baseLat"], shop["baseLng"], lat, lng)
    miles = road_miles(straight, t.get("roadFactor", 1.25))
    rt = t["roundTrip"] if round_trip is None else round_trip
    in_range = miles <= t["maxDriveMiles"]
    mph = t.get("avgMph", 38)

    tiers = t.get("tiers") or []
    if tiers:
        distance_fee, breakdown = tiered_miles_fee(tiers, miles)
        zone = None
        billable = round(sum(b["miles"] for b in breakdown), 1)
    else:
        zone = zone_for_miles(catalog, miles)
        billable = max(0.0, miles - t["freeMiles"])
        per_mile_fee = round(billable * t["perMileAfterFree"], 2)
        zone_fee = zone["fee"] if zone else 0.0
        distance_fee = max(per_mile_fee, zone_fee, t["minimumFee"])
        breakdown = [{"from": t["freeMiles"], "to": miles, "miles": billable,
                      "perMile": t["perMileAfterFree"], "amount": per_mile_fee}]
    if not in_range:
        distance_fee = 0.0  # outside service area -> handled by a custom quote

    drive_minutes = round(miles / mph * 60)
    on_site_minutes = drive_minutes if rt else 0
    drive_time_hours = round((drive_minutes + on_site_minutes) / 60, 2)

    surcharges = []
    when = when or datetime.now()
    if t.get("afterHoursSurcharge"):
        if when.hour < 8 or when.hour >= 18:
            surcharges.append({"label": "After-hours call (before 8am / after 6pm)",
                               "amount": t["afterHoursSurcharge"]})
    if t.get("weekendSurcharge") and when.weekday() == 6:
        surcharges.append({"label": "Sunday call", "amount": t["weekendSurcharge"]})

    total = round(distance_fee + sum(s["amount"] for s in surcharges), 2)
    if straight < 0.5:
        miles = 0.0
    return {
        "inServiceArea": in_range,
        "base": f"{shop['baseAddress']}",
        "straightLineMiles": round(straight, 1),
        "miles": miles,
        "roundTrip": rt,
        "zone": zone["name"] if zone else None,
        "freeMiles": t["freeMiles"],
        "billableMiles": billable,
        "tiers": breakdown,
        "perMileFee": distance_fee,
        "zoneFee": 0,
        "distanceFee": round(distance_fee, 2),
        "driveMinutesOneWay": drive_minutes,
        "driveMinutesTotal": drive_minutes + on_site_minutes,
        "driveHoursTotal": drive_time_hours,
        "driveTimeValue": round(drive_time_hours * t["driveTimeValuePerHour"], 2),
        "surcharges": surcharges,
        "travelFee": total,
        "maxDriveMiles": t["maxDriveMiles"],
    }


# ---------------------------------------------------------------- line items

def _find_item(catalog: dict, item_id: str) -> dict | None:
    for cat in catalog["categories"]:
        for item in cat["items"]:
            if item["id"] == item_id:
                return {**item, "category": cat["name"]}
    for pkg in catalog["packages"]:
        if pkg["id"] == item_id:
            return {**pkg, "category": "Packages"}
    for add in catalog["addons"]:
        if add["id"] == item_id:
            return {**add, "category": add["group"]}
    return None


QUESTION_SETS = {
    "sunroof": {"id": "sunroof", "label": "Does your car have a sunroof?",
                "type": "choice", "options": ["Yes", "No", "Panoramic"], "required": True},
    "parts": {"id": "parts", "label": "Who supplies the parts?",
              "type": "choice", "options": ["I'll source them", "I'm bringing my own"], "required": True},
    "lift": {"id": "lift", "label": "Where will the car be?",
             "type": "choice", "options": ["Driveway / street", "Garage with a lift"], "required": True},
    "tune": {"id": "tune", "label": "What are you running now?",
             "type": "choice", "options": ["Stock", "Stage 1", "Stage 2", "FBO / custom"],
             "hint": "Tells me what the car needs before I flash it.", "required": True},
    "datalog": {"id": "datalog", "label": "Do you have a datalog to send?",
                "type": "choice", "options": ["Yes, I have logs", "No, need to pull them"], "required": True},
    "cosmetic": {"id": "cosmetic", "label": "Parts for this install",
                 "type": "choice", "options": ["I'll bring the parts", "Need you to source them"], "required": True},
    "symptoms": {"id": "symptoms", "label": "What's it doing?",
                 "type": "text", "hint": "Warning lights, noises, codes, when it happens.", "required": True},
    "repairparts": {"id": "repairparts", "label": "Parts for this repair",
                    "type": "choice", "options": ["I'll bring OEM", "Need you to source them"], "required": True},
    "custom": {"id": "custom", "label": "Tell me what you have in mind",
               "type": "textarea", "required": True},
    "photos": {"id": "photos", "label": "Photos (optional)",
               "type": "note", "hint": "You can email photos to bimmerhousecalls@gmail.com after you submit."},
}

# category id -> questions every item in it asks
CATEGORY_QUESTIONS = {
    "tuning": ["tune"],
    "exhaust": ["parts"],
    "intake": ["parts"],
    "cooling": ["parts"],
    "suspension": ["lift", "parts"],
    "cosmetic": ["cosmetic"],
    "starlights": ["sunroof"],
    "maintenance": [],
    "repairs": ["symptoms", "repairparts"],
}
ITEM_QUESTIONS = {
    "ecu-bench-unlock": ["tune"],
    "stage1-tune": ["tune"],
    "stage2-tune": ["tune"],
    "datalog-review": ["datalog"],
    "ppi": ["symptoms"],
    "diagnostics": ["symptoms"],
    "starlight-headliner": ["sunroof"],
    "starlight-twinkle": ["sunroof"],
    "starlight-shooting": ["sunroof"],
}


def questions_for(catalog: dict, item_ids: list[str], package: str | None = None,
                  custom: bool = False) -> list[dict]:
    """Only the questions the selected services actually need."""
    want: list[str] = []
    if custom:
        want += ["custom", "photos"]
    for item_id in ([package] if package else []) + list(item_ids):
        for cat in catalog["categories"]:
            if any(i["id"] == item_id for i in cat["items"]):
                want += CATEGORY_QUESTIONS.get(cat["id"], [])
        want += ITEM_QUESTIONS.get(item_id, [])
    seen, out = set(), []
    for qid in want:
        if qid not in seen and qid in QUESTION_SETS:
            seen.add(qid)
            out.append(QUESTION_SETS[qid])
    return out


def price_item(catalog: dict, item_id: str, model_variant: int = 0, variant_count: int = 1) -> dict:
    """Price one catalog item.

    Published prices are ranges. When a model has several variants (e.g. N20 vs
    N55 vs S55) the range is split evenly across them so a 4-cyl and an M car do
    not land on the same number; the owner can override any line afterwards.
    """
    item = _find_item(catalog, item_id)
    if item is None:
        raise KeyError(f"unknown item: {item_id}")
    if item.get("quote") or item.get("min") is None:
        return {
            "id": item_id, "name": item["name"], "desc": item.get("desc", ""),
            "category": item.get("category"), "min": None, "max": None,
            "unitPrice": None, "needsQuote": True, "qty": 1, "total": None,
        }
    lo, hi = float(item["min"]), float(item["max"])
    n = max(1, variant_count)
    step = (hi - lo) / n if n > 1 else 0
    idx = min(max(model_variant, 0), n - 1)
    unit = round(lo + step * idx, 2) if n > 1 else round((lo + hi) / 2, 2)
    return {
        "id": item_id, "name": item["name"], "desc": item.get("desc", ""),
        "category": item.get("category"), "min": lo, "max": hi,
        "unitPrice": unit, "needsQuote": False, "qty": 1, "total": unit,
    }


# ---------------------------------------------------------------- quote build

@dataclass
class QuoteLine:
    id: str
    name: str
    qty: float = 1
    unit: float = 0.0
    kind: str = "service"      # service | addon | package | travel | fee | discount | parts
    note: str = ""


@dataclass
class Quote:
    client: dict
    vehicle: dict
    scheduled_at: str | None
    lines: list = field(default_factory=list)
    parts: list = field(default_factory=list)
    taxRate: float = 0.0
    depositPercent: float = 25.0
    notes: str = ""

    def subtotal(self) -> float:
        return round(sum(l.qty * l.unit for l in self.lines if l.kind != "discount"), 2)

    def discount_total(self) -> float:
        return round(sum(l.qty * l.unit for l in self.lines if l.kind == "discount"), 2)

    def parts_total(self) -> float:
        return round(sum(p["qty"] * p["unit"] for p in self.parts), 2)

    def taxable_base(self, tax_labor: bool) -> float:
        base = self.parts_total()
        if tax_labor:
            base += self.subtotal() - self.discount_total()
        return round(base, 2)

    def totals(self, tax_labor: bool = False, custom: bool = False,
               deposit_percent: float | None = None) -> dict:
        sub = self.subtotal()
        disc = self.discount_total()
        parts = self.parts_total()
        tax_base = parts + (sub - disc if tax_labor else 0)
        tax = round(tax_base * self.taxRate, 2)
        total = round(sub - disc + parts + tax, 2)
        pct = self.depositPercent if deposit_percent is None else deposit_percent
        # Deposit only on custom orders; standard menu jobs are paid on completion.
        # A custom build with no price yet (TBD line) still owes a deposit — it is
        # collected against the final quote, so the deposit stays 0 until the owner
        # prices the job. Once anything is priced, the 25% applies.
        deposit = max(round(total * pct / 100, 2), 0) if (custom and total > 0) else 0.0
        return {
            "subtotal": sub, "discount": disc, "parts": parts,
            "taxRate": self.taxRate, "tax": tax, "total": total,
            "deposit": deposit, "balance": round(total - deposit, 2),
        }


def labor_hours(catalog: dict, item_ids: list[str]) -> float:
    hours = 0.0
    for item_id in item_ids:
        item = _find_item(catalog, item_id)
        if item:
            hours += float(item.get("laborHours", 2))
    return round(hours, 2)


def in_hours(catalog: dict, start: datetime, hours: float) -> bool:
    """Is this whole job inside a working window that day?"""
    windows = (catalog["shop"].get("hours") or {}).get(str((start.weekday() + 1) % 7), [])
    end = start + timedelta(hours=hours)
    for a, b in windows:
        open_t = start.replace(hour=int(a[:2]), minute=int(a[3:]), second=0, microsecond=0)
        close_t = start.replace(hour=int(b[:2]), minute=int(b[3:]), second=0, microsecond=0)
        if open_t <= start and end <= close_t:
            return True
    return False


def next_open_slot(catalog: dict, hours: float, after: datetime | None = None) -> datetime:
    """First moment on the calendar where the job fits, honoring shop hours."""
    t = (after or datetime.now()) + timedelta(days=1)
    t = t.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=30)
    for _ in range(60 * 24):
        for hh in range(6, 18):
            cand = t.replace(hour=hh, minute=0)
            if in_hours(catalog, cand, hours):
                return cand
        t += timedelta(days=1)
    return t


def slot_for(catalog: dict, item_ids: list[str], start: datetime) -> dict:
    """Booking slot: job length + a 30 min buffer, drive time added by the caller.
    A slot outside shop hours is pushed to the next time the job actually fits."""
    h = max(labor_hours(catalog, item_ids), 0.5)
    if not in_hours(catalog, start, h):
        start = next_open_slot(catalog, h, start - timedelta(days=1))
    end = start + timedelta(hours=h) + timedelta(minutes=30)
    return {"start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
            "hours": h}


def vin_decode_stub(vin: str) -> dict:
    """Offline VIN parse. Real decoding needs an API key; this gets model family,
    engine guess and year, which is enough to price and to flag what to confirm."""
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        return {"valid": False, "error": "A VIN is 17 characters."}
    year_codes = "ABCDEFGHJKLMNPRSTVWXY123456789"
    try:
        year = 1980 + year_codes.index(vin[9])
    except ValueError:
        year = None
    if year and year < 1990:
        year += 30
    return {
        "valid": True,
        "vin": vin,
        "wmi": vin[:3],
        "year": year,
        "plant": vin[10],
        "serial": vin[11:],
        "needsModelConfirm": True,
        "note": "Year and plant decoded offline. Engine/model confirmed by VIN lookup or by the owner.",
    }


if __name__ == "__main__":
    cat = load_catalog()
    print("shop:", cat["shop"]["name"])
    tq = travel_quote(cat, 40.2171, -74.7429)   # Trenton
    print("Trenton travel:", json.dumps(tq, indent=2))
    print("oil service:", price_item(cat, "oil-service"))
    q = Quote(client={"name": "Test"}, vehicle={"vin": "WBA3A5C55CF256789"}, scheduled_at=None,
              taxRate=cat["shop"]["taxRateNJ"])
    for line in (price_item(cat, "oil-service"), price_item(cat, "brake-pads-rotors")):
        q.lines.append(QuoteLine(line["id"], line["name"], unit=line["unitPrice"] or 0))
    q.lines.append(QuoteLine("travel", "Travel fee", unit=tq["travelFee"], kind="travel"))
    print("totals:", q.totals())
