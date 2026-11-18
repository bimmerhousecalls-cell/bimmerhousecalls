# Sending email through the Gmail API (free, works on Render's free tier)

Google renamed and moved everything in 2025. **There is no "OAuth consent
screen" menu any more.** It is now called **Google Auth Platform**, and it is
split into four tabs: **Branding**, **Audience**, **Data Access**, **Clients**.

That is why you cannot find it.

Your Gmail app password is correct — Render's free tier blocks the SMTP ports it
needs. The Gmail API sends over ordinary web traffic instead.

---

## What it affects

**Nothing visible to customers.** Same sender address, same name, same emails,
same invoices.

Three things on your end:

1. **One new variable** in Render: `BHC_GOOGLE_REFRESH_TOKEN`.
2. **It can expire.** A token issued while the app is in "Testing" dies every
   **7 days**. You must publish the app (step 5). Otherwise email stops weekly.
3. **The app password stays**, it just is not what sends your mail.

---

## Step 1 — get to the right place

You have already made the project and enabled the Gmail API. Good.

Now, in the left menu of the Cloud Console:

- Look for **APIs & Services** → you will see **OAuth consent screen** in the
  list. **Clicking it takes you to "OAuth overview"** — that is the new page.
- The four tabs you need are down the **left side of that page**:
  **Branding · Audience · Data Access · Clients**

If you cannot find it, type this straight into the browser:

```
https://console.cloud.google.com/auth/overview
```

---

## Step 2 — Branding

1. Left sidebar → **Branding**
2. **Get started** (or **Edit** if it already exists)
3. App name: `Bimmer House Calls`
4. User support email: `bimmerhousecalls@gmail.com`
5. Logo: skip it
6. Audience / user type: **External** → **Next**
7. Developer contact email: `bimmerhousecalls@gmail.com` → **Next**
8. **Create**

---

## Step 3 — Data Access (the scope)

1. Left sidebar → **Data Access**
2. **Add or remove scopes**
3. In the filter box type `gmail.send`
4. Tick the row ending in `/auth/gmail.send`
5. **Update** → **Save**

---

## Step 4 — Audience (add yourself)

1. Left sidebar → **Audience**
2. Make sure it says **External**
3. Scroll to **Test users** → **Add users**
4. `bimmerhousecalls@gmail.com` → **Save**

---

## Step 5 — Clients (get the ID and secret)

1. Left sidebar → **Clients**
2. **Create client**
3. Application type: **Web application**
4. Name: `Bimmer House Calls Web`
5. **Authorized redirect URIs** → **Add URI** → paste exactly:

```
https://bimmerhousecalls.onrender.com/oauth/callback
```

6. **Create**
7. A box shows the **Client ID** and **Client secret**. Copy both.

---

## Step 6 — put them in Render and connect

1. Render → your service → **Environment** → add three variables:

| Key | Value |
|---|---|
| `BHC_GOOGLE_CLIENT_ID` | the Client ID |
| `BHC_GOOGLE_CLIENT_SECRET` | the Client secret |
| `BHC_OAUTH_REDIRECT` | `https://bimmerhousecalls.onrender.com/oauth/callback` |

2. Save, wait for the redeploy
3. Open in your browser:

```
https://bimmerhousecalls.onrender.com/oauth/start
```

4. Sign in as `bimmerhousecalls@gmail.com`
5. Google says "Google hasn't verified this app" → **Advanced** → **Go to
   Bimmer House Calls (unsafe)**. That is normal for your own app.
6. Tick **Send email on your behalf** → **Continue**
7. The page shows a long string labelled **BHC_GOOGLE_REFRESH_TOKEN**. Copy it.

---

## Step 7 — publish the app (do not skip)

Without this the token dies every 7 days.

1. **Google Auth Platform** → **Audience**
2. Under **Publishing status: Testing** → **Publish app** → **Confirm**

Google will not demand verification: the only scope is `gmail.send`, used by you
alone. Publishing just removes the 7-day expiry.

---

## Step 8 — give Render the token

1. Render → Environment → add:

| Key | Value |
|---|---|
| `BHC_GOOGLE_REFRESH_TOKEN` | the long string you copied |

2. Delete `BHC_GOOGLE_CLIENT_ID`, `BHC_GOOGLE_CLIENT_SECRET` and
   `BHC_OAUTH_REDIRECT` — only needed to obtain the token.
3. Save, redeploy

---

## Step 9 — prove it works

Open:

```
https://bimmerhousecalls.onrender.com/api/email-status
```

You want `"sender": "gmail-api"`. Then in your dashboard click
**Send a test email to myself**.

---

## If it stops working

Open `/api/email-status` and read `problem`:

- **"refresh token is expired or revoked"** — the app was left in Testing.
  Do step 7, then step 6 again for a fresh token.
- **"No sender configured"** — the variable did not save.

---

## Limits

About **500 recipients a day** on a personal Gmail account. A busy day for you is
10–20.
