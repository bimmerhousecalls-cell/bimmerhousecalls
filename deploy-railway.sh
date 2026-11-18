#!/bin/sh
# Put this backend online WITHOUT git.
#
# Railway takes a folder straight from this computer: no GitHub, no repository,
# no upload form. You run one command and it deploys what is here.
#
#   sh deploy-railway.sh
#
# First run: it installs the Railway command-line tool into tools/, opens your
# browser to log in, creates the project, deploys, and prints your public URL.
#
cd "$(dirname "$0")" || exit 1

echo "== Bimmer House Calls — deploy to Railway =="
echo

# 1. Is Node here? (the Railway CLI needs it)
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. The Railway tool runs on it."
  echo
  echo "Install the LTS version from https://nodejs.org (click the big green"
  echo "button, run the installer, then run this script again)."
  echo
  echo "Alternative with nothing to install: create a free GitHub account, make a"
  echo "repository called bimmerhousecalls, click 'uploading an existing file' and"
  echo "drag the files from this folder in. Then in Render choose 'Public Git"
  echo "repository' and paste that repository's address. See DEPLOY.md."
  exit 1
fi

# 2. Install the CLI into tools/ so nothing global is touched
if [ ! -f tools/node_modules/.bin/railway ] && [ ! -f tools/node_modules/.bin/railway.cmd ]; then
  echo "Installing the Railway tool (once, about 30 seconds)…"
  mkdir -p tools
  ( cd tools && npm init -y >/dev/null 2>&1 && npm install --no-audit --no-fund @railway/cli ) || {
    echo "Install failed. Check your internet connection and run this again."; exit 1; }
fi

RAILWAY=tools/node_modules/.bin/railway
[ -f tools/node_modules/.bin/railway.cmd ] && RAILWAY=tools/node_modules/.bin/railway.cmd

# 3. Log in (opens your browser)
echo
echo "Opening your browser to log in to Railway. If you do not have an account,"
echo "sign up with Google or email — it is free."
"$RAILWAY" login || { echo "Login did not finish. Run this script again."; exit 1; }

# 4. Create the project and deploy this folder
echo
echo "Creating the project and uploading the files…"
"$RAILWAY" init --name bimmerhousecalls || true
"$RAILWAY" up || { echo "Deploy failed. Run 'sh deploy-railway.sh' again to see the error."; exit 1; }

# 5. Generate a public address
echo
echo "Giving the service a public address…"
"$RAILWAY" domain 2>/dev/null || echo "Could not make a domain automatically — do it in the Railway dashboard: your service → Settings → Networking → Generate Domain."

echo
echo "== Done. Your booking page is at:  <your-address>/book =="
echo
echo "Next: set these in the Railway dashboard → your service → Variables:"
echo "  BHC_ADMIN_KEY   your admin password (do not leave it blank)"
echo "  BHC_BASE_URL    the address Railway just gave you"
echo
echo "Then point your Netlify Book buttons at <your-address>/book — see CHANGE-BOOK-LINKS.md"
