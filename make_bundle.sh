#!/bin/sh
# Turn this folder into ONE deployable unit: dist/bimmerhousecalls-site.zip
# Contains the code, your service catalog, the brand theme, the pages and an
# empty database. Upload the zip to any host that runs Python (Render, Railway,
# Fly, a VPS, DigitalOcean App Platform) — see DEPLOY.md.
# To put it online without git, read GOING-ONLINE-NO-GIT.md.
# For the Render settings, read RENDER-CONFIGURE.md.
# To point your Netlify Book buttons at it, read CHANGE-BOOK-LINKS.md.
cd "$(dirname "$0")" || exit 1
mkdir -p dist
python - <<'PY'
import os, zipfile, json, shutil, tempfile, datetime

root = os.getcwd()
out = os.path.join("dist", "bimmerhousecalls-site.zip")
skip_dirs = {"__pycache__", "dist", "backups", "outbox", ".git", "work"}
skip_files = {"bhc.sqlite3", "api.pid", "api.log", "DEPLOY.local.md"}

count = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for f in files:
            if f in skip_files or f.endswith((".log", ".pid", ".pyc", "-shm", "-wal")):
                continue
            p = os.path.join(base, f)
            rel = os.path.relpath(p, root)
            z.write(p, rel)
            count += 1

print(f"{out}  —  {count} files, {os.path.getsize(out) // 1024} KB")
print("Includes: app/ (API + pages), data/services.json (catalog, theme, hours),")
print("          bhc.sh, requirements.txt, Procfile, DEPLOY.md")
PY
