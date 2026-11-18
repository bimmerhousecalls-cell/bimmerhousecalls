# GOING LIVE — step by step

Written for your situation: marketing site on Netlify, backend = this folder, email
from bimmerhousecalls@gmail.com, and you want it free.

---

## Part 1 — Your "Book now" button (5 minutes, no cost)

Your Netlify site stays exactly as it is. You only change where its buttons point.

**Every button that should start a booking must link to your app, not to a form.**
In Netlify → your site → **Site configuration → Build & deploy → Post processing** (or
in your HTML/React source), the button becomes:

```html
<a class="btn" href="https://app.bimmerhousecalls.com/book">Book now</a>
```

`/book`, `/book-now`, `/booking` and `/` all open the booking page, so any of those
links work. If you cannot give the app its own subdomain yet, point it at the
temporary address your host gives you (Part 3).

Then add two more links while you are in there:

| Button | Points to |
|---|---|
| Book now | `https://app.bimmerhousecalls.com/book` |
| Owner / Manage | `https://app.bimmerhousecalls.com/admin` (your key: `BMWM340I#$`) |

So: **yes** — Book now takes the client straight into the backend booking page, they
pick services, see the travel fee and drive time live, sign your terms, and you get
the email. They never see a form that goes nowhere.

---

## Part 2 — What you need before you start

1. The bundle: `dist/bimmerhousecalls-site.zip` (rebuild any time with
   `sh make_bundle.sh`).
2. A free Render account (render.com) — no card needed on the free tier.
3. Your Gmail app password (so the server can send mail without me):
   Google Account → **Security** → turn on 2-Step Verification → **App passwords** →
   create one for "Mail" → copy the 16 characters.

---

## Part 3 — Put it online on Render (free)

1. **render.com → Sign up** (GitHub or email).
2. **New +** → **Web Service**.
3. Choose **Deploy an existing image or public repo** → or simply drag the zip when
   Render offers "Upload". If Render asks for a repo instead, make a free GitHub repo
   and upload the unzipped folder to it (drag and drop on github.com → New repository).
4. Fill the form:
   - **Name:** `bimmerhousecalls`
   - **Region:** Ohio (closest to New Jersey)
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python -m app.api.server`
   - **Instance type:** Free
5. **Environment variables** (Advanced → Add Environment Variable):

   | Key | Value |
   |---|---|
   | `BHC_ADMIN_KEY` | `BMWM340I#$` |
   | `BHC_BASE_URL` | `https://bimmerhousecalls.onrender.com` (change later to your domain) |
   | `BHC_SMTP_USER` | `bimmerhousecalls@gmail.com` |
   | `BHC_SMTP_PASS` | the 16-character Gmail app password |

   Do **not** set `PORT` — Render does that itself.
6. **Create Web Service**. First build takes ~2 minutes. You get
   `https://bimmerhousecalls.onrender.com`.
7. Open it: the booking page loads, `/admin` asks for your key, `BMWM340I#$` gets you in.
8. **Custom domain:** Settings → Custom Domains → add `app.bimmerhousecalls.com`.
   Render shows a CNAME. In Netlify: **Domain management → DNS records → Add record**,
   type CNAME, name `app`, value the one Render gave you. Wait 10–30 minutes. HTTPS is
   automatic. Then update `BHC_BASE_URL` to `https://app.bimmerhousecalls.com` and
   redeploy (Manual Deploy → Deploy latest commit).
9. Point your Netlify Book now button at that domain (Part 1).

**Free-tier reality:** the app sleeps after 15 minutes of no visitors and takes ~30
seconds to wake on the first click. A paid instance (~$7/month) never sleeps. The
software costs nothing either way.

---

## Part 4 — Turn on automatic email on the server

Free Render has no cron, so use **Render Cron Jobs** (free tier includes them) or a
free scheduler like cron-job.org hitting a URL. Two options:

**A. Render Cron Job** — New + → Cron Job, same repo, command:

```sh
python -m app.services.mailer
```

Schedule `*/5 * * * *`. A second cron job at `0 7 * * *` running
`python -m app.services.mailer --digest` sends your morning summary.

**B. cron-job.org (free)** — add a job that POSTs every 5 minutes to
`https://app.bimmerhousecalls.com/api/run/mailer` with the header
`X-Admin-Key: BMWM340I#$`. Other jobs you can schedule the same way:
`/api/run/digest` (7am), `/api/run/archive` (nightly), `/api/run/automation` (hourly).
All of them refuse to run without the header.

Meanwhile, the 7am routine in this app already does it while your computer is on.

---

## Invoices: you set the final price

The client's estimate is only a starting point. In the dashboard, **Settings →
Invoices** lists every invoice with **Edit** and **Email it**:

- change quantities and prices, add a line (parts, extra labor, a trip), delete one,
- add a note to the client ("parts came in higher, added a second hour"),
- **Save** to keep it as a draft, or **Save & email it** to send it right then.

Nothing is emailed automatically unless the client signed a custom build (deposit
invoice) — the balance invoice waits for you to send it, so you can price the job
first. Once a payment is recorded the invoice locks; issue a new one for a change.

## Travel fee: one way

The fee is for the drive **to the job only** — not the drive home. 37 miles to Point
Pleasant is billed as 37 miles ($5.25), not 74. There is no after-hours or Sunday
surcharge.

## Part 5 — Keep your records

- **In the app:** `/admin` → Settings → **File finished jobs now** writes
  `work/YYYY-MM/JOB_Client/` with the job sheet, invoices, signature record and emails.
- **Backups:** on the server the database lives in `data/bhc.sqlite3`. On a free Render
  instance the disk resets when it redeploys — so either:
  - add a free persistent disk in Render (Settings → Disks, 1 GB), or
  - download `data/bhc.sqlite3` before any redeploy, or
  - use `/admin` → Settings → **Download the database** (built in — one click).
- Keep the local folder here as your master copy; `./bhc.sh backup` zips it.

---

## Part 6 — The things I would add next (your call)

Ranked by what actually saves you money or grief:

1. **Card payments online** — not now, by your call. Invoices ask the client to pay by
   Zelle/cash/check, which is free. When you want it later: Stripe, no monthly fee,
   ~2.9% + 30¢ per payment.
2. **Text reminders** — the day-before email gets opened maybe 40% of the time; a text
   gets read. Twilio is ~$1/month per number plus a penny a message.
3. **Persistent storage on the host** — so the database survives redeploys (Part 5).
4. **Google Calendar sync** — jobs appear in your phone's calendar automatically.
5. **Real VIN decode** — right now the VIN is validated and stored; the NHTSA decoder
   is free and would auto-fill model/year for the client.
6. **Actual drive time** — currently distance ÷ average speed. Google's Distance Matrix
   gives real minutes and is free up to 200 calls/month, then pay-per-use.
7. **A lead-notification text to your phone** — so a new request buzzes your pocket,
   not just your inbox.
8. **Multi-car clients / service history per VIN** — "your last oil change was 6,200
   miles ago" in the reminder email.
9. **A price book page** — your 34 services with starting prices, so people can browse
   without starting a booking.

Say the number and I will build it.
