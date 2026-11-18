# Bimmer House Calls — backend

Booking, quoting, **travel fees from Surf City LBI**, e-signed terms, invoices,
payments and automated email — everything Check Cherry does for an event
business, rebuilt for a mobile BMW tech, plus what it can't do (VIN-gated quotes,
tiered mileage, driveway-vs-lift warnings).

Plain Python 3, no packages to install, SQLite for storage.

```
bimmerhousecalls/
  app/
    api/server.py        HTTP API + serves the booking page, client portal and dashboard
    db.py                SQLite schema (clients, vehicles, bookings, proposals, invoices,
                         payments, emails, templates, meta, audit)
    services/
      pricing.py         travel tiers, drive time, quote lines, conditional questions, VIN parse
      booking.py         lead -> quote -> proposal -> e-sign -> invoice -> payment
      terms.py           versioned Terms & Conditions + tuning waiver (hashed)
      emails.py          17 email templates + trigger rules + queue
      worker.py          sends the queue (console, or Gmail via BHC_GMAIL_CMD)
      automation.py      the cron job: reminders, follow-ups, balance invoices, expiry
      flow.py            end-to-end demo of the whole money path
    static/
      index.html         booking page — category tabs, conditional questions, live travel fee
      proposal.html      client portal: quote + answers + terms + signature pad
      invoice.html       client portal: invoice + payments
      admin.html         owner dashboard (/admin)
  data/services.json     catalog, prices, travel tiers — edit this
  run_api.sh             start/restart the API
```

## Run it

```bash
./run_api.sh                                  # API + all pages on http://localhost:8080
python -m app.services.automation             # every 5 min: send emails, reminders, invoices
```

| Page | What |
|---|---|
| `http://localhost:8080/` | the booking page your clients use |
| `http://localhost:8080/admin` | **owner dashboard** — overview, bookings, invoices, emails, settings |
| `http://localhost:8080/p/<token>` | client proposal: quote, their answers, terms, signature |
| `http://localhost:8080/i/<token>` | client invoice |

Set `BHC_ADMIN_KEY=something` before starting the server to require a key on
`/api/admin/*` and on the dashboard. Without it, any key opens it (fine on your
own computer, never on the public internet).

## Hours & calendar

```json
"hours": {"0": [], "1": [["07:00","17:00"]], "2": [["07:00","17:00"]], "3": [["07:00","17:00"]],
          "4": [["07:00","17:00"]], "5": [["06:00","15:00"]], "6": [["06:00","15:00"]]},
"hoursLabel": "Mon–Thu 7am–5pm · Fri–Sat 6am–3pm · Sunday closed"
```

(0 = Sunday.) The booking page only offers slots inside those hours, only ones that
fit the job's length, and only ones that don't collide with a job already booked —
Sundays show as closed. The dashboard has a **Calendar** tab: month grid, closed days
greyed, jobs colored by status, click one to open it.

## Invoices — you send them, or they go out on their own

Both. On the dashboard you can **create an invoice for any amount and email it in one
click** (`Invoice` tab on a booking, or "Send invoice" on the Invoices list). And these
send automatically:

- a custom build → deposit invoice the moment they sign
- a finished standard job → balance invoice the day after
- a payment recorded → receipt to the client and an alert to you

## Your terms, and the signature gate

`terms.py` holds **your** Terms and Conditions verbatim (22 sections + Customer
Acknowledgment and Waiver), with your draft's bracketed items filled from
`services.json` (quote valid 7 days, 24-hour cancellation, 30-day workmanship
warranty, Ocean County, hours, accepted payment methods). Nothing is booked until
the client:

1. scrolls the full terms in the portal,
2. ticks **"I have read and agree to the Terms and Conditions"**,
3. ticks the **electronic signature consent**, and
4. draws a signature and types their legal name.

The API refuses the signature without both boxes (`consent` + `acknowledged`), and
the signature record stores the name, image, time, IP, user agent, terms version and
a hash of the exact document. Bump `TERMS_VERSION` in `terms.py` whenever you edit
the text — old signed versions stay intact.

## Brand colors

Primary **#FFD400** on contrast **#0B0B0D**. Navigation bar #0B0B0D with white text.
Every call-to-action button is #FFD400 with #0B0B0D text. Defined once in
`services.json → shop.theme`; the booking page, proposal, invoice and dashboard all
read it.

## Terms before the request

The client cannot send a request without agreeing: the booking page shows the full
Terms and Conditions in a scroll box, with two checkboxes (agree to terms, agree to
electronic signature), a typed legal name and a drawn signature. The API rejects a
request without `consent` + `acknowledged` + signature, and the signature is recorded
with the terms version and a hash.

## Colors

The dashboard, booking page and portals all read the palette in
`services.json → shop.theme` (`ink`, `accent`, `bg`, `navBg`, …). Change the accent to
your site's blue and every page follows.

## Owner alerts

You get an email on every new request, every signature, and every recorded payment —
so a lead never sits unseen in the dashboard.

## Deposits

**No deposit on menu jobs** — the client signs, it's booked, and they pay when the
work is done (balance invoice goes out the day after the job). **Custom builds**
take a 25% deposit before parts are ordered. Both are settings in `services.json`
(`depositPercent: 0`, `depositPercentCustom: 25`).

## Travel fee (from Surf City, LBI)

```json
"travel": { "freeMiles": 30,
            "tiers": [ {"upToMiles": 30, "perMile": 0},
                       {"upToMiles": 60, "perMile": 0.75},
                       {"upToMiles": null, "perMile": 1.50} ],
            "maxDriveMiles": 120, "roundTrip": true, "avgMph": 38, "roadFactor": 1.25 }
```

Marginal tiers: the first 30 miles are free, 30–60 miles bill at $0.75/mi, past 60
at $1.50/mi. A 45-mile job pays for 15 miles; a 70-mile job pays 30 at .75 plus 10
at 1.50. Distance is straight-line × 1.25 for real roads, and every quote shows the
client the miles, the drive time and the fee line-by-line before they book.

Examples: Toms River 25 mi → free · Point Pleasant 37 mi → $5.25 · Freehold 52 mi →
$16.58 · Trenton 61 mi → $24.15 · Newark 93 mi → $71.55.

## Conditional questions

Only the questions the selected work needs are asked, and they're stored on the
booking and shown on the proposal:

| Pick | Asked |
|---|---|
| Tuning / ECU unlock | current tune state (stock / stage 1 / stage 2 / FBO) |
| Datalog review | do you have logs |
| Starlights | sunroof yes / no / panoramic |
| Exhaust, intake, cooling, suspension | who supplies parts; suspension also driveway or lift |
| Cosmetic | bringing parts or source them |
| Repairs, diagnostics, PPI | symptoms + who supplies parts |
| Custom build | what you have in mind + photos note |

Edit `QUESTION_SETS` / `CATEGORY_QUESTIONS` in `pricing.py` to change them.

## Automations

| Trigger | Email |
|---|---|
| request submitted | quote + link to sign (now) |
| 48h unsigned | reminder (cancelled the moment they sign) |
| signed, menu job | "you're booked" + day-before at 5pm + review ask the day after |
| signed, custom build | deposit invoice |
| day after a finished job | balance invoice + email |
| 14 days after an unsigned quote | follow-up |
| owner reschedules / cancels | reschedule / cancellation notice |
| owner invoices, records a payment | invoice email, receipt |

Default sender prints to the console so nothing is lost. For real mail, set
`BHC_GMAIL_CMD` to a command that reads `{"to","subject","body"}` JSON on stdin and
sends it (Gmail API `users.messages.send` as bimmerhousecalls@gmail.com).

## Owner dashboard (`/admin`)

Overview (collected, outstanding, confirmed jobs, open quotes, next up, email
queue) · Bookings with status filters and a per-booking drawer (details, their
answers, lines, money, invoices, email history) · **Send an invoice for any
amount and email it** · record cash / Zelle / check / card payments · resend a
quote · reschedule · cancel · send a one-off email · retry a failed email ·
Settings showing every price and the travel tiers.

## API

| Method | Path | What |
|---|---|---|
| POST | `/api/quote` | price a job without creating anything (items, addons, package, custom, lat/lng, when, answers) |
| POST | `/api/request` | create client + vehicle + booking + proposal, queue emails (17-char VIN + email required) |
| GET | `/api/catalog` | services, add-ons, packages, travel rules |
| GET | `/api/availability?date=` | open slots from real bookings |
| GET | `/api/p/{token}` · POST `.../sign` · `.../decline` | client portal + e-signature |
| GET | `/api/i/{token}` | invoice + payments |
| POST | `/api/admin/{action}` | `summary`, `bookings`, `booking`, `invoice.create`, `invoice.email`, `proposal.resend`, `payment.record`, `reschedule`, `cancel`, `email.send`, `email.retry` |

Send `X-Admin-Key` on admin calls when `BHC_ADMIN_KEY` is set.

## E-signature

Signing records the typed name, the drawn signature image, timestamp, IP, user
agent, the terms version and a SHA-256 of the exact document, so any agreement can
be reprinted and proven. `terms.py` holds the text (liability, tuning/warranty
waiver, parts, travel, cancellation, NJ UETA consent) — bump `TERMS_VERSION` when
you change it.

## Still to wire (needs your accounts, not code)

- **Stripe** checkout on the invoice page (button is in place; needs your keys)
- **Gmail sending** — `BHC_GMAIL_CMD` hook is ready; needs the OAuth app password/API
- **Real VIN decode** (NHTSA vPIC is free) to replace the offline year/plant parse
- **Geocoding** — ships with NJ ZIP/city centroids; swap for a geocoder for exact addresses
- **SMS** (Twilio) on the same triggers
