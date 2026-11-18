"""Persistence layer — SQLite, zero install.

One file holds clients, vehicles, bookings, proposals, signatures, invoices,
payments, emails, templates and settings. `db()` gives a connection with
row access by name and foreign keys on.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # .../bimmerhousecalls/app
ROOT = os.path.dirname(_HERE)                                            # .../bimmerhousecalls
# Where the database lives. On a host, point BHC_DATA_DIR at a mounted disk so
# data survives a redeploy; without one it sits beside the code.
_DATA_DIR = os.environ.get("BHC_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.environ.get("BHC_DB") or os.path.join(_DATA_DIR, "bhc.sqlite3")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT,
  phone TEXT,
  address TEXT,
  city TEXT,
  state TEXT DEFAULT 'NJ',
  zip TEXT,
  lat REAL, lng REAL,
  source TEXT DEFAULT 'website',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS clients_email_uniq ON clients(lower(email)) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
  vin TEXT NOT NULL,
  year INTEGER,
  model TEXT,
  engine TEXT,
  variant_index INTEGER DEFAULT 0,
  sunroof INTEGER DEFAULT 0,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS vehicles_vin_uniq ON vehicles(vin);
CREATE INDEX IF NOT EXISTS vehicles_client ON vehicles(client_id);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE,
  client_id INTEGER REFERENCES clients(id),
  vehicle_id INTEGER REFERENCES vehicles(id),
  status TEXT NOT NULL DEFAULT 'lead',
  -- lead | quoted | proposal_sent | signed | deposit_paid | confirmed | in_progress | done | cancelled
  scheduled_start TEXT,
  scheduled_end TEXT,
  travel_miles REAL,
  travel_fee REAL DEFAULT 0,
  travel_json TEXT,
  job_hours REAL,
  request_json TEXT,       -- what they asked for, raw
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS bookings_start ON bookings(scheduled_start);

CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
  number TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'draft',
  -- draft | sent | viewed | signed | declined | expired
  lines_json TEXT NOT NULL DEFAULT '[]',
  parts_json TEXT NOT NULL DEFAULT '[]',
  totals_json TEXT NOT NULL DEFAULT '{}',
  terms_version TEXT,
  terms_hash TEXT,
  public_token TEXT UNIQUE,
  expires_at TEXT,
  sent_at TEXT,
  viewed_at TEXT,
  signed_at TEXT,
  signature_name TEXT,
  signature_image TEXT,     -- data URL of the drawn signature
  signature_ip TEXT,
  signature_ua TEXT,
  signed_hash TEXT,         -- sha256 of the exact signed document
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
  proposal_id INTEGER REFERENCES proposals(id),
  number TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'open',  -- open | partial | paid | void
  totals_json TEXT NOT NULL DEFAULT '{}',
  due_at TEXT,
  public_token TEXT UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
  amount REAL NOT NULL,
  kind TEXT DEFAULT 'deposit',   -- deposit | balance | payment
  method TEXT,                    -- card | cash | zelle | check | other
  processor TEXT,                 -- stripe | paypal | manual
  processor_ref TEXT,
  received_at TEXT NOT NULL DEFAULT (datetime('now')),
  note TEXT
);

CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  template TEXT,
  booking_id INTEGER REFERENCES bookings(id),
  status TEXT NOT NULL DEFAULT 'queued',  -- queued | sent | failed | skipped
  error TEXT,
  scheduled_for TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS emails_status ON emails(status, scheduled_for);

CREATE TABLE IF NOT EXISTS templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,          -- terms | email | contract_block
  slug TEXT NOT NULL,
  version TEXT NOT NULL,
  body TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(kind, slug, version)
);

CREATE TABLE IF NOT EXISTS meta (
  entity TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY (entity, entity_id, key)
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  actor TEXT,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id INTEGER,
  detail TEXT
);
"""


def db() -> sqlite3.Connection:
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)   # idempotent: every statement is IF NOT EXISTS
    return conn


def init(path: str | None = None) -> None:
    global DB_PATH
    if path:
        DB_PATH = path
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('initialized_at', ?)",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"),))


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


if __name__ == "__main__":
    init()
    print("initialized", DB_PATH)
