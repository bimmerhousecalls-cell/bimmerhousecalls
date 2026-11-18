# Put the backend online — the no-git way

Render's screen only offers "Git provider" or "Public Git repository". That is
true: **Render cannot take a zip.** So pick one of these two routes.

---

## Route A — GitHub, drag and drop (free, no tools to install, ~10 minutes)

You never touch a command line. GitHub's website has an upload page.

**1. Make a free account** at https://github.com/signup (email + password).

**2. Make a repository.** Top right **+** → **New repository**.
- Name: `bimmerhousecalls`
- Leave it **Public** (Render's free tier reads public repos; private also works
  but public is simpler)
- Do **not** tick "Add a README"
- Click **Create repository**

**3. Upload the files.** On the new page click **"uploading an existing file"**
(the link is in the sentence "…or upload an existing file").
- Unzip `bimmerhousecalls-site.zip` somewhere first.
- Open the unzipped folder, select **everything inside it** (not the folder
  itself) and drag it onto the upload page.
- Wait for all 33 files to list, then click **Commit changes**.

**4. Deploy on Render.** https://render.com → sign up with GitHub (free) →
**New +** → **Web Service** → pick `bimmerhousecalls` → then:

| Setting | Value |
|---|---|
| Language | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m app.api.server` |
| Instance Type | **Free** |

**5. Add the settings.** Under **Environment** add:

| Key | Value |
|---|---|
| `BHC_ADMIN_KEY` | your admin password — pick something strong |
| `BHC_BASE_URL` | the URL Render gives you (add it after step 6) |

**6. Deploy.** Render builds for a minute or two, then gives you a URL like
`https://bimmerhousecalls.onrender.com`. Open it — you should see your booking
page. The booking page is that URL **+ `/book`**.

**7. Point Netlify at it.** See `CHANGE-BOOK-LINKS.md`.

> Free tier note: the site sleeps after 15 minutes of no visitors and takes
> about 30–50 seconds to wake. The first visitor of the day waits. Everything
> else is free.

---

## Route B — Railway, straight from your computer (no GitHub)

Railway accepts a folder uploaded from this computer. It needs Node.js
installed once.

1. Install Node.js LTS from https://nodejs.org (green button, run installer).
2. In this folder run: `sh deploy-railway.sh`

The script installs Railway's tool, opens your browser to log in, creates the
project, uploads the files, and prints your public address.

---

## Which should you pick?

**Route A.** It is the one you can do entirely with clicking, it is the one
Render's free tier is built for, and the files are already prepared for it
(`Procfile`, `runtime.txt`, `requirements.txt` are in the zip).

---

## After it is live

1. Open `<your-url>/admin` and log in with your `BHC_ADMIN_KEY`.
2. Do one real booking with your own email and walk through the quote,
   signature, invoice and dashboard.
3. Set `BHC_BASE_URL` to your real address so email links are absolute.
4. **Back up after your first real job.** Free hosts have no permanent disk —
   a redeploy wipes the database. Dashboard → **Download the database** first.
   When you outgrow that, a $7/month disk on Render fixes it permanently.
