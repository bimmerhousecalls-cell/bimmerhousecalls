# Your Netlify site — where to change the booking links

Open your site's code (or Netlify → Site → Deploys → the repo/file you edit) and
find `index.html`. It is one file. There are exactly **six** places to change.

## The one rule

Every "Book" button must point at your backend with `/book` on the end.

```
https://YOUR-BACKEND-URL/book
```

Not the backend root, not `/admin`. `/book` is the booking page.

Right now every one of these buttons is a `#` or goes nowhere.

---

## The six places in index.html

Search the file for `href="#"` — you will land on each one.

### 1. The big hero button ("Book Now")

Find:
```html
<a class="btn" href="#">Book Now</a>
```
Change to:
```html
<a class="btn" href="https://YOUR-BACKEND-URL/book">Book Now</a>
```

### 2. The nav bar "Book"

Find:
```html
<a href="#">Book</a>
```
Change to:
```html
<a href="https://YOUR-BACKEND-URL/book">Book</a>
```

### 3. The package cards — "Book This"

Each of the three packages has one. They are `onclick="..."` or `href="#"`.
Change each to:
```html
<a class="btn" href="https://YOUR-BACKEND-URL/book">Book This</a>
```

If a package should pre-select itself in the booking page, add the package id:
```
https://YOUR-BACKEND-URL/book?package=essential
```
(Use `essential`, `complete`, or `annual` — tell me if your package ids differ and
I will make the backend read them.)

### 4. "Book Online" in the "Book Your Visit" section

Find:
```html
<a href="#">Book Online</a>
```
Change to:
```html
<a href="https://YOUR-BACKEND-URL/book">Book Online</a>
```

### 5. "Submit a Request Online" (custom work)

Find:
```html
<a href="#">Submit a Request Online</a>
```
Change to:
```html
<a href="https://YOUR-BACKEND-URL/book#custom">Submit a Request Online</a>
```
`#custom` opens the booking page already switched to Custom Work.

### 6. The footer, if it has a booking link

Same change: `href="#"` → `href="https://YOUR-BACKEND-URL/book"`.

---

## Nothing else changes

- Phone and email links stay as they are.
- The Services, FAQ, Packages sections stay on Netlify — they are your menu.
- You do **not** upload the backend to Netlify. The backend goes to Render (or
  Railway / Fly). Netlify keeps serving the marketing site; it just links across.

## After you deploy the backend

1. Open the backend URL — you should see the booking page.
2. Copy that URL, add `/book`, paste it into the six places above.
3. Redeploy Netlify.
4. Click every Book button on the live site and confirm each one lands on the
   booking page.

## If you would rather not edit code

Send me the URL once the backend is live and I will write the exact replacement
lines for your file, ready to paste.

---

## While you are in there — two small improvements worth making

1. **The FAQ says "Parts orders require a deposit."** That now matches the
   backend: deposits are for custom orders only, 25%. Menu jobs take no deposit.
2. **Travel fee wording.** The site says "Travel fee may apply outside the Jersey
   Shore area." The backend is precise: first 30 miles free, then $0.75/mile to
   60, then $1.50/mile beyond. You may want to say so — customers like knowing
   the rule before they book.
