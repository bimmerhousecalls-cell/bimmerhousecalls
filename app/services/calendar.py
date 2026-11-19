"""Put a confirmed booking on the owner's Google Calendar.

A booking is created with its own event on the shop's calendar, so the owner
sees the job on their phone: who, where, what car, what work, how much, and
how far they have to drive. Colours come from the job category so a quick
glance separates an oil service from a brake job.

The event id is stored on the booking so a reschedule or cancel updates or
removes the same event instead of creating a second one.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# Google Calendar event colours, picked per service category.
CATEGORY_COLORS = {
    "maintenance": "2",    # green
    "performance": "7",    # blue
    "cosmetic": "3",       # purple
    "diagnostics": "5",    # yellow
    "repairs": "11",       # red
    "custom": "6",         # orange
}
DEFAULT_COLOR = "8"        # grey


def _cfg() -> dict:
    return {"refresh": os.environ.get("BHC_GOOGLE_REFRESH_TOKEN", ""),
            "cid": os.environ.get("BHC_GOOGLE_CLIENT_ID", "").strip(),
            "csec": os.environ.get("BHC_GOOGLE_CLIENT_SECRET", "").strip(),
            "calendar": os.environ.get("BHC_CALENDAR_ID", "primary")}


def _access_token() -> str | None:
    """Reuse the Gmail refresh token — it already carries the client id when packed."""
    import base64
    c = _cfg()
    if not c["refresh"]:
        return None
    cid, csec = c["cid"], c["csec"]
    if c["refresh"].startswith("json:") and not cid:
        try:
            blob = json.loads(base64.urlsafe_b64decode(c["refresh"][5:] + "===").decode())
            cid = blob.get("client_id", "")
            csec = blob.get("client_secret", "")
        except Exception:  # noqa: BLE001
            return None
    if not cid:
        return None
    data = urllib.parse.urlencode({"client_id": cid, "client_secret": csec,
                                   "refresh_token": c["refresh"],
                                   "grant_type": "refresh_token"}).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    return bool(_cfg()["refresh"])


def _request(method: str, path: str, payload: dict | None = None) -> dict | None:
    tok = _access_token()
    if not tok:
        return None
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(_cfg()['calendar'], safe='')}/{path}"
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {tok}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError:
        return None
    except Exception:  # noqa: BLE001
        return None


def _colour_for(categories: list[str]) -> str:
    for cat in categories or []:
        if cat in CATEGORY_COLORS:
            return CATEGORY_COLORS[cat]
    return DEFAULT_COLOR


def _address(booking_row, client_row) -> str:
    """Where to drive: the booking's own address if it has one, else the client's."""
    try:
        own = booking_row["service_address"]
    except (IndexError, KeyError):
        own = ""
    if own:
        return own
    parts = [client_row["address"] if "address" in client_row.keys() else "",
             client_row["city"] if "city" in client_row.keys() else "",
             client_row["state"] if "state" in client_row.keys() else "",
             client_row["zip"] if "zip" in client_row.keys() else ""]
    return ", ".join(p for p in parts if p)


def build_event(booking_row, client_row, vehicle_row, quote: dict, lines: list[dict]) -> dict:
    """Everything the owner needs at a glance when they open the event."""
    shop = quote.get("shop") or {}
    cats = [str(items).lower() for items in (quote.get("categories") or [])]
    start = datetime.fromisoformat(booking_row["scheduled_start"])
    hours = float(booking_row["job_hours"] or 2)
    end = start + timedelta(hours=hours)

    work = "\n".join(
        f"• {l.get('name', 'Service')} — ${float(l.get('total', 0)):.2f}" for l in lines) or "• To be confirmed"
    travel = ""
    if booking_row["travel_miles"]:
        travel = (f"\n\nDrive: {float(booking_row['travel_miles']):.1f} mi each way "
                  f"— travel fee ${float(booking_row['travel_fee'] or 0):.2f}")

    description = (
        f"Client: {client_row['name']}\n"
        f"Phone: {client_row['phone'] or ''}\n"
        f"Email: {client_row['email']}\n"
        f"Address: {_address(booking_row, client_row)}\n\n"
        f"Vehicle: {vehicle_row['year'] or ''} {vehicle_row['model'] or ''}".rstrip() + "\n"
        f"VIN: {vehicle_row['vin']}\n\n"
        f"Work:\n{work}"
        f"{travel}\n\n"
        f"Booking {booking_row['code']}"
    )

    summary = f"{client_row['name']} — {vehicle_row['model'] or 'BMW'} ({hours:g}h)"
    return {
        "summary": summary,
        "description": description,
        "location": _address(booking_row, client_row),
        "start": {"dateTime": start.isoformat(timespec="seconds"),
                  "timeZone": shop.get("timezone", "America/New_York")},
        "end": {"dateTime": end.isoformat(timespec="seconds"),
                "timeZone": shop.get("timezone", "America/New_York")},
        "colorId": _colour_for(cats),
        "reminders": {"useDefault": False,
                      "overrides": [{"method": "popup", "minutes": 60},
                                    {"method": "popup", "minutes": 1440}]},
    }


def create(booking_row, client_row, vehicle_row, quote: dict, lines: list[dict]) -> str | None:
    """Create the event; returns its id so it can be updated or deleted later."""
    if not available():
        return None
    res = _request("POST", "events", build_event(booking_row, client_row, vehicle_row, quote, lines))
    return (res or {}).get("id")


def update(event_id: str, booking_row, client_row, vehicle_row, quote: dict, lines: list[dict]) -> bool:
    if not (available() and event_id):
        return False
    return _request("PUT", f"events/{urllib.parse.quote(event_id)}",
                    build_event(booking_row, client_row, vehicle_row, quote, lines)) is not None


def delete(event_id: str) -> bool:
    if not (available() and event_id):
        return False
    return _request("DELETE", f"events/{urllib.parse.quote(event_id)}") is not None
