"""Backups — one zip of everything that matters, dated, in backups/.

    python -m app.services.backup

Includes the database (clients, vehicles, bookings, signatures, invoices,
payments, email log) and the service catalog. Skips logs, the outbox and the pid.
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make() -> str:
    out_dir = os.path.join(ROOT, "backups")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"bhc-{datetime.now().strftime('%Y%m%d-%H%M')}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(os.path.join(ROOT, "data")):
            dirs[:] = [d for d in dirs if d not in ("outbox", "__pycache__")]
            for f in files:
                if f.endswith((".log", ".pid", ".pyc")):
                    continue
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, ROOT))
    return out


if __name__ == "__main__":
    path = make()
    print(f"Backup: {path}  ({os.path.getsize(path) // 1024} KB)")
