# Going live

The whole site is one folder. `sh make_bundle.sh` packs it into
`dist/bimmerhousecalls-site.zip` — code, your catalog, your brand colors, your hours,
your terms, the booking page, the client portals and the owner dashboard. No database
libraries, no build step, no npm: plain Python 3.

Right now it runs on this computer at **http://localhost:8080** (booking page at `/`,
your dashboard at `/admin`). "Live" means putting that same folder on a server that
stays on, so clients can reach it from their phones at your real domain.

---

## Option A — the easiest real host (Render, ~10 minutes)

1. Sign up at render.com and choose **New → Web Service**.
2. Upload the zip (or push the folder to GitHub and point Render at it).
3. Settings:
   - **Environment:** Python 3
   - **Build command:** `pip install -r requirements.txt` (nothing to install, but it keeps Render happy)
   - **Start command:** `python -m app.api.server`
   - **Environment variables:**
     - `PORT` — Render sets this automatically; the app reads it.
     - `BHC_ADMIN_KEY` — pick a long password. **Do this.** It locks `/admin`.
     - `BHC_BASE_URL` — `https://yourdomain.com` (so emailed links are correct).
4. Deploy. Render gives you `https://bimmerhousecalls.onrender.com`.
5. **Custom domain:** Render → Settings → Custom Domain → add
   `app.bimmerhousecalls.com`, then add the CNAME record it shows at your domain
   registrar (Netlify DNS, in your case: Site settings → Domain management → DNS).
   HTTPS is automatic.

Railway, Fly.io and DigitalOcean App Platform work the same way — the start command
is the only thing that matters.

## Option B — a $5 VPS you control

```sh
ssh you@your-server
sudo apt install python3 -y
scp -r bimmerhousecalls/ you@your-server:/srv/
cd /srv/bimmerhousecalls && ./bhc.sh start          # runs on :8080
sudo apt install caddy -y                            # HTTPS + reverse proxy
echo 'app.bimmerhousecalls.com { reverse_proxy localhost:8080 }' | sudo tee /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

Caddy gets a free certificate for the domain, so `https://app.bimmerhousecalls.com`
serves your booking page and dashboard. Add a systemd unit if you want it to survive
reboots (`bhc.sh start` in `ExecStart`).

## Option C — keep your Netlify site, put the app behind it

Your Netlify page stays the marketing front door. Point its **Book now** buttons at
`https://app.bimmerhousecalls.com/` and its owner link at `/admin`. Netlify can't run
Python itself, so the app needs one of the hosts above — but the visitor never sees
the difference: same brand, one click.

---

## Before you take real bookings

| Do this | Why |
|---|---|
| Set `BHC_ADMIN_KEY` | Without it anyone who finds `/admin` can read your clients |
| Set `BHC_BASE_URL` to your real domain | Emails currently link to `localhost`, which your clients can't open |
| Wire the email sender (see below) | Otherwise confirmations sit in the queue |
| `./bhc.sh check` | 18 automated checks over pages, pricing, hours, signature gate, invoices, admin |
| `./bhc.sh backup` | Zips `data/` — run it before any change, and keep the zips somewhere else |

---

## Email — how it actually sends

Your Gmail (`bimmerhousecalls@gmail.com`) is connected to this bot, so **the bot is the
sender**. Two ways to run it:

**1. From the bot (works today).** Ask the bot to "send the queued emails". It runs
`python -m app.services.mailer --outbox`, which writes each due email to
`data/outbox/`, sends them from your Gmail, and marks them sent. I tested it — the
test message is in your inbox.

**2. Fully automatic on the server.** Set one of these environment variables on the
host:

```sh
# Gmail app password (Google Account → Security → 2-Step Verification → App passwords)
BHC_SMTP_USER=bimmerhousecalls@gmail.com
BHC_SMTP_PASS=abcd efgh ijkl mnop
```

With those set, `./bhc.sh emails` sends without the bot. Add it to cron:

```cron
*/5 * * * * cd /srv/bimmerhousecalls && ./bhc.sh emails >> data/mailer.log 2>&1
0 7 * * *   cd /srv/bimmerhousecalls && ./bhc.sh digest >> data/mailer.log 2>&1
```

The queue is in SQLite, so a failed send is never lost — it retries on the next pass.

**What sends, and when:**

| Trigger | To client | To you |
|---|---|---|
| New request (with signature) | quote + confirmation | "New request" alert |
| Signature | — (already signed at request) | "signed — booked" alert |
| Custom build | deposit invoice | payment alert |
| Day before the job | reminder | — |
| Job finished | balance invoice | — |
| Payment recorded | receipt | "Payment $X" alert |
| 2 days after the job | review request | — |
| Every morning 7am | — | today's jobs, requests waiting, money owed |

---

## Backups and moving the site

- `./bhc.sh backup` → `backups/bhc-YYYYMMDD-HHMM.zip` (database + catalog).
- To move hosts: copy the folder, drop your latest `bhc.sqlite3` back into `data/`,
  `./bhc.sh start`. Client history, signatures and invoices come with it.
- Signatures are stored with the exact terms version and a SHA-256 hash of the
  document that was signed, so a signed agreement can always be proven.

## Your dashboard password

The dashboard is **locked**. The key is stored with the site, so it works the same on
your laptop and on the server:

```sh
./bhc.sh password            # prints it
./bhc.sh password MyNewKey   # changes it
```

Type it once at `/admin` — the browser remembers it if you leave "Keep me signed in"
ticked. On a host, you can instead set `BHC_ADMIN_KEY` as an environment variable; that
wins over the stored one.

Current key for this install: `bhc_yMnZ0diOQ4H2Mo8NHsXj3f7Z` — change it before the
site is public.

## Keeping track of the work

| Where | What's in it |
|---|---|
| `/admin` | live view: calendar, bookings, invoices, email queue, money collected/owed |
| `work/YYYY-MM/JOB_Client/` | one folder per finished job: `job.txt` (client, car, VIN, when, services, travel fee, drive time, total), `invoice-*.txt`, `signature-*.txt` (name, time, IP, terms version, document hash), `emails.txt` |
| `backups/bhc-YYYYMMDD-HHMM.zip` | the whole database, dated — `./bhc.sh backup` |
| `data/outbox/` | every email as sent, as HTML |

`./bhc.sh archive` files every finished job (also a button in Settings). The 7am
routine does it every morning, so the folders stay current without you thinking
about it.

## Cost

Nothing in this build costs money:

- No paid services, no npm packages, no database server — Python's standard library
  and a single SQLite file.
- Your Gmail sends the mail. No mail service, no monthly fee.
- Free hosting that runs it: Render's free tier, Railway's trial, Fly.io's allowance,
  or your own computer with a free tunnel while you test. A custom domain is the only
  thing you might pay for (about $12/year at a registrar), and you already have
  `bimmerhousecalls.netlify.app` — a Netlify subdomain is free.
- The one thing to know: free tiers sleep after inactivity, so the first visit of the
  day takes ~30 seconds to wake. A paid instance (about $7/month) stays warm. Nothing
  about the software requires paying.

## What "one file" means here

You asked for everything in one file. Practically, the whole site is **one folder you
can zip, copy and upload** — `make_bundle.sh` produces it. It is not one single
`.py` file, and that is deliberate: a 3,000-line file with the pages, the pricing, the
terms and the dashboard crammed in is where bugs hide and where a change to your
colors breaks your invoices. The folder is the unit of deployment; the pieces are
small and named (`pricing.py`, `terms.py`, `emails.py`, `admin.html`).

## Before your first real customer

The database is empty as of 2026-11-18 — every test client, booking, quote,
invoice and queued email was cleared. The menu, terms, colors and admin
password were kept.

If test data creeps back in while you are trying things out, clear it in one
click: **Dashboard → Your records → "Start clean — delete all test data"**.
(Or `curl -X POST /api/admin/database.reset -H 'X-Admin-Key: ...' -d '{"confirm":"RESET"}'`.)

Then, in order:

1. **Set the admin password** on the server: `./bhc.sh password 'your-key'` or the
   `BHC_ADMIN_KEY` environment variable. Never leave the default.
2. **Set `BHC_BASE_URL`** to your real address, so links in emails are absolute.
3. **Add `BHC_SMTP_USER` and `BHC_SMTP_PASS`** (Gmail app password) so client email
   sends itself. Without them, run `./bhc.sh emails` to send from the outbox.
4. **Point your site's Book Now button** at `https://your-host/book`.
5. **Take a backup** after your first real job: `./bhc.sh backup`.
