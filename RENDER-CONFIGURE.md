# Render "Configure" screen — what to put in each box

You are on the screen that asks for a Name, Region, Branch, Root Directory,
Build Command, Start Command and Instance Type. Here is every field.

---

## Name

Whatever you like — it becomes part of your address.

```
bimmerhousecalls
```

→ your address will be `https://bimmerhousecalls.onrender.com`
(if the name is taken, Render adds a suffix; that is fine)

## Region

Pick the one closest to New Jersey:

```
Ohio (US East)
```

Any US East option is fine. Do not pick Europe or Asia — every page would be slow.

## Branch

```
main
```

Leave it as whatever it defaulted to if it says `main` or `master`.

## Root Directory

**Leave it completely empty.** Your files are at the top of the repo
(`app/`, `data/`, `Procfile` are at the top level). Putting anything here will
break the build.

## Runtime / Language

```
Python 3
```

If it asks for a version, leave it on the default.

## Build Command

```
pip install -r requirements.txt
```

This does nothing harmful — your app needs no packages — but Render expects a
command and this one succeeds instantly.

## Start Command

```
python -m app.api.server
```

**This one matters most.** If it says `gunicorn app:app` or anything else,
replace it with exactly the line above.

## Instance Type

```
Free
```

## Environment Variables — how to add them

This is the one screen people get stuck on. It is not a file you edit; it is a
form in Render's website.

**Where:** open your service in Render → the **Environment** tab in the left
menu (older screens call it "Environment Variables"). You will see an empty list
with an **+ Add Environment Variable** button.

**How:** click **+ Add Environment Variable**. Two boxes appear:

- **Key** — the name, typed exactly as below (capital letters, underscores)
- **Value** — the secret or address

Click **+ Add Environment Variable** again for the next one. When you are done,
click **Save Changes** — Render redeploys by itself with the new values.

### The two you need

| Key | Value | What it is |
|---|---|---|
| `BHC_ADMIN_KEY` | a password you invent | Your dashboard login at `/admin`. Make it long. Not `BMWM340I#$`, not anything you have used elsewhere. |
| `BHC_BASE_URL` | `https://bimmerhousecalls.onrender.com` | Your real address, no trailing slash. Makes links inside client emails point at the live site instead of localhost. |

### Needed for email (add these three and it works)

| Key | Value | What it does |
|---|---|---|
| `BHC_SMTP_USER` | `bimmerhousecalls@gmail.com` | Turns on automatic sending |
| `BHC_SMTP_PASS` | a Gmail **app password** | The 16-character password |
| `BHC_DATA_DIR` | `/var/data` | Only if you attach a paid disk, so data survives redeploys |

**Getting the Gmail app password** (your normal password will not work):

1. myaccount.google.com → **Security**
2. Turn on **2-Step Verification** if it is off
3. In the search box at the top, type **App passwords**
4. Name it `Bimmer House Calls` → **Create**
5. Google shows 16 characters like `abcd efgh ijkl mnop` — copy them **without spaces**
6. Paste that as `BHC_SMTP_PASS`

Then in the dashboard click **"Send a test email to myself"**. It tells you plainly
whether it worked, and the exact error if it did not.

### About "API keys"

You do not need any. There is no Stripe key (you are taking Zelle, cash and
checks), no Google Maps key (the travel fee uses built-in NJ ZIP coordinates),
and no database key (it is a local SQLite file). The only secret in the whole
app is `BHC_ADMIN_KEY`.

If you ever do want automatic email, the Gmail app password is the one key to
get: Google Account → Security → 2-Step Verification → App passwords → create
one called "Bimmer House Calls" → paste the 16 characters as `BHC_SMTP_PASS`.

## Health Check Path

Leave blank. Your app has no health endpoint and adding one will fail the deploy.

---

## Then

Click **Deploy Web Service**. It builds for 1–3 minutes. Watch the log; when it
says `Listening on` and the status turns **Live**, open your URL.

- `https://YOUR-URL/` → booking page
- `https://YOUR-URL/admin` → dashboard (log in with `BHC_ADMIN_KEY`)
- `https://YOUR-URL/book` → the link for your Netlify buttons

---

## If the deploy fails

Look for the last red line in the log and match it here:

| Message | Fix |
|---|---|
| `No such file or directory: 'requirements.txt'` | Root Directory is not empty — clear it |
| `Error: No start command` / `Application failed to respond` | Start Command is not `python -m app.api.server` |
| `Exited with status 1` right at the start | Open the log above it — usually a Python syntax or path error; send me the line |
| `Port already in use` | Render sets `PORT` itself; make sure Start Command is exactly as above |
| Build succeeds but page is blank | Wait 50 seconds — the free tier sleeps, and the first visit wakes it |

Send me the failing lines and I will tell you the exact fix.
