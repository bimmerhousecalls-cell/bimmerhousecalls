"""Print or change the dashboard admin key.

    python -m app.services.admin_key            # show it
    python -m app.services.admin_key my-new-key # set it

Stored in the database, so it works the same on your laptop and on the server.
BHC_ADMIN_KEY in the environment wins over this if you set it on a host.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import db as dbmod
from app.services import booking


def main() -> None:
    dbmod.init()
    new = sys.argv[1] if len(sys.argv) > 1 else None
    with dbmod.db() as conn:
        if new:
            booking.meta_set(conn, "settings", 0, "admin_key", new)
            print(f"New admin key: {new}")
        else:
            print(f"Admin key: {booking.meta_get(conn, 'settings', 0, 'admin_key') or '(none set)'}")


if __name__ == "__main__":
    main()
