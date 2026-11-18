# Connect your Netlify site to the booking backend

Your backend is live and working:
**https://bimmerhousecalls.onrender.com/book** ← this is the address.

Everything below is on the Netlify side. You edit one file.

---

## Step 1 — open the right file on Netlify

Two ways, pick whichever you have:

**A. You have a Git repo for the site**
Edit `index.html` in that repo, commit, and Netlify redeploys.

**B. You upload the site by hand (Netlify Drop)**
1. Find the folder on your computer with your website's `index.html`.
2. Open it in Notepad, VS Code, or any text editor.
3. Make the changes below.
4. Save, then drag the whole folder onto https://app.netlify.com/drop again.

Either way it is **one file**: `index.html`.

---

## Step 2 — find every dead booking button

In `index.html`, search for this:

```
href="#"
```

You will hit the Book buttons. Each one needs the address above. There are six.

### 2a. The hero "Book Now"

```html
<a class="btn" href="#">Book Now</a>
```
becomes
```html
<a class="btn" href="https://bimmerhousecalls.onrender.com/book">Book Now</a>
```

### 2b. The nav bar "Book"

```html
<a href="#">Book</a>
```
becomes
```html
<a href="https://bimmerhousecalls.onrender.com/book">Book</a>
```

### 2c. The three package "Book This" buttons

Each one becomes:
```html
<a class="btn" href="https://bimmerhousecalls.onrender.com/book">Book This</a>
```

To have a package already selected when the booking page opens:
```html
<a class="btn" href="https://bimmerhousecalls.onrender.com/book?package=essential">Book This</a>
```
Use `essential`, `complete`, or `annual`.

### 2d. "Book Online"

```html
<a href="https://bimmerhousecalls.onrender.com/book">Book Online</a>
```

### 2e. "Submit a Request Online" (custom work)

```html
<a href="https://bimmerhousecalls.onrender.com/book#custom">Submit a Request Online</a>
```
`#custom` opens the booking page already switched to Custom build.

### 2f. Any footer booking link

Same address: `https://bimmerhousecalls.onrender.com/book`

---

## Step 3 — the fast way to do all six

If your buttons are all the same shape, you can do it in one pass:

1. Open `index.html` in a text editor.
2. Press **Ctrl+H** (find and replace).
3. Find: `href="#"` — Replace: `href="https://bimmerhousecalls.onrender.com/book"`
4. **Replace all**.
5. Save and upload.

That catches every dead button at once. It is safe as long as `href="#"` only
appears on booking buttons — check the file first by scrolling through the
matches.

---

## Step 4 — test it

Open your live site and click each Book button. Every one should land on the
booking page at `bimmerhousecalls.onrender.com/book`.

If it lands on a blank page or an error, the address is mistyped — check for a
missing `https://` or a trailing slash.

---

## One thing you cannot change

Netlify cannot host the backend. Netlify serves files; the booking page needs a
running Python program. That is why the buttons point at Render.

The two stay separate on purpose:
- **Netlify** — your menu, photos, FAQ, prices, story
- **Render** — booking, quotes, signatures, invoices, your dashboard

---

## Bonus: point a subdomain at it later (optional)

If you ever buy `bimmerhousecalls.com`, you can make it look professional:

- `bimmerhousecalls.com` → stays on Netlify (the marketing site)
- `book.bimmerhousecalls.com` → the Render backend

Then your buttons read `https://book.bimmerhousecalls.com/book`. Ask me when you
want to do this; it is a DNS record and one setting in Render.
