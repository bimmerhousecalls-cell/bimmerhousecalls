"""Render an invoice to a PDF so it can ride along with the email.

No external tools: a small, self-contained PDF writer good enough for a branded
one-page invoice. If anything goes wrong the email still goes out with its link,
so this never blocks a send.
"""
from __future__ import annotations

import json
import os
import textwrap

PAGE_W, PAGE_H = 595, 842          # A4 in points
MARGIN = 48
INK = (0.043, 0.043, 0.051)
YELLOW = (1.0, 0.831, 0.0)
MUTED = (0.36, 0.39, 0.44)


def _esc(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(str(text or ""), width=width) or [""]


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = PAGE_H - MARGIN

    def text(self, x: float, y: float, size: float, text: str, colour=INK, bold=False) -> None:
        font = "F2" if bold else "F1"
        clean = (str(text) or "").replace("·", "-").replace("×", "x").replace("—", "-")
        self.ops.append(f"BT {colour[0]:.3f} {colour[1]:.3f} {colour[2]:.3f} rg "
                        f"/{font} {size:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(clean)}) Tj ET")

    def rect(self, x: float, y: float, w: float, h: float, colour) -> None:
        self.ops.append(f"{colour[0]:.3f} {colour[1]:.3f} {colour[2]:.3f} rg "
                        f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def line(self, x1: float, y1: float, x2: float, y2: float, grey=0.85) -> None:
        self.ops.append(f"{grey:.2f} {grey:.2f} {grey:.2f} RG 0.7 w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def room(self, need: float) -> bool:
        return self.y - need > MARGIN


def _pdf(pages: list[_Page]) -> bytes:
    """Assemble a minimal, valid PDF from the drawing operations.

    Object layout: 1 catalog, 2 pages, then one page/content pair per page,
    then the two fonts last so every reference points at a real object.
    """
    font1 = 3 + len(pages) * 2
    font2 = font1 + 1
    objs: list[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode())
    for i, page in enumerate(pages):
        page_no = 3 + i * 2
        content_no = page_no + 1
        objs.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
             f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
             f"/Contents {content_no} 0 R >>").encode())
        stream = "\n".join(page.ops).encode("latin-1", "replace")
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                    + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n"
            f"{xref_at}\n%%EOF\n").encode()
    return bytes(buf)


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def build_pdf(inv: dict) -> bytes:
    """Draw the invoice: header, bill-to, vehicle, work, totals, terms footer."""
    pages = [_Page()]
    p = pages[0]

    # black header band with the shop name
    p.rect(0, PAGE_H - 96, PAGE_W, 96, INK)
    p.rect(0, PAGE_H - 100, PAGE_W, 4, YELLOW)
    shop = inv.get("shop") or {}
    p.text(MARGIN, PAGE_H - 46, 20, shop.get("name") or "Bimmer House Calls", (1, 1, 1), bold=True)
    p.text(MARGIN, PAGE_H - 66, 9, "Mobile BMW service & performance",
           (0.78, 0.80, 0.84))
    p.text(MARGIN, PAGE_H - 82, 9,
           f"{shop.get('phone', '')} · {shop.get('email', '')}", (0.78, 0.80, 0.84))
    p.text(PAGE_W - MARGIN - 120, PAGE_H - 46, 13, "INVOICE", (1, 1, 1), bold=True)
    p.text(PAGE_W - MARGIN - 120, PAGE_H - 64, 10, str(inv.get("number", "")), YELLOW, bold=True)

    y = PAGE_H - 128
    p.text(MARGIN, y, 9, "BILLED TO", MUTED, bold=True)
    p.text(PAGE_W - MARGIN - 150, y, 9, "AMOUNT DUE", MUTED, bold=True)
    y -= 16
    client = inv.get("client") or {}
    p.text(MARGIN, y, 11, client.get("name", ""), bold=True)
    due = (inv.get("totals") or {}).get("amountDue", 0)
    p.text(PAGE_W - MARGIN - 150, y, 15, _money(due), bold=True)
    y -= 14
    for bit in (client.get("address", ""), client.get("phone", ""), client.get("email", "")):
        if bit:
            p.text(MARGIN, y, 9, bit, MUTED)
            y -= 12
    y -= 8
    p.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 20

    veh = inv.get("vehicle") or {}
    p.text(MARGIN, y, 9, "VEHICLE", MUTED, bold=True)
    y -= 14
    yr = str(veh.get("year") or "").strip()
    if not (yr.isdigit() and 1980 <= int(yr) <= 2100):
        yr = ""
    line = " ".join(x for x in (yr, veh.get("model", "")) if x).strip() or "BMW"
    p.text(MARGIN, y, 11, line)
    if veh.get("vin"):
        p.text(MARGIN + 200, y, 9, f"VIN {veh['vin']}", MUTED)
    y -= 24

    title = (inv.get("jobTitle") or "").strip()
    if title:
        p.rect(MARGIN, y - 2, 3, 13, YELLOW)
        p.text(MARGIN + 10, y, 9, "THE WORK", MUTED, bold=True)
        y -= 16
        for wl in _wrap(title, 80):
            p.text(MARGIN + 10, y, 11.5, wl, bold=True)
            y -= 15
        y -= 12

    p.text(MARGIN, y, 9, "SERVICES", MUTED, bold=True)
    p.text(PAGE_W - MARGIN - 120, y, 9, "AMOUNT", MUTED, bold=True)
    y -= 6
    p.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 16
    for ln in inv.get("lines") or []:
        if not p.room(70):
            pages.append(_Page())
            p = pages[-1]
            y = p.y
        name = str(ln.get("name", "Service"))
        qty = ln.get("qty", 1)
        label = f"{name}" + (f"  ×{qty:g}" if float(qty or 1) != 1 else "")
        for wl in _wrap(label, 62):
            p.text(MARGIN, y, 10.5, wl)
            y -= 13
        amt = ln.get("total")
        if not amt and ln.get("qty") and ln.get("unit"):
            amt = float(ln["qty"]) * float(ln["unit"])
        p.text(PAGE_W - MARGIN - 120, y + 13, 10.5, _money(amt))
        y -= 6
    y -= 4
    p.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 18

    t = inv.get("totals") or {}
    for label, val, bold in (("Subtotal", t.get("subtotal", 0), False),
                             ("Total", t.get("total", 0), True),
                             ("Amount due", t.get("amountDue", 0), True)):
        p.text(PAGE_W - MARGIN - 190, y, 10.5 if not bold else 11.5, label, bold=bold)
        p.text(PAGE_W - MARGIN - 120, y, 10.5 if not bold else 11.5, _money(val), bold=bold)
        y -= 16

    notes = (inv.get("notes") or "").strip()
    if notes:
        y -= 8
        p.text(MARGIN, y, 9, "NOTES", MUTED, bold=True)
        y -= 15
        for wl in _wrap(notes, 88):
            if not p.room(40):
                pages.append(_Page())
                p = pages[-1]
                y = p.y
            p.text(MARGIN, y, 10, wl)
            y -= 13

    # footer with payment instructions
    foot = pages[-1]
    foot.line(MARGIN, MARGIN + 46, PAGE_W - MARGIN, MARGIN + 46)
    accepts = ", ".join(shop.get("accepts") or ["Cash", "Check"])
    foot.text(MARGIN, MARGIN + 32, 9, f"HOW TO PAY  ·  {accepts.upper()}", MUTED, bold=True)
    foot.text(MARGIN, MARGIN + 6, 8, "Nothing is charged online. Terms and your signature are on record.",
              MUTED)
    return _pdf(pages)


def render(public_token: str) -> str:
    """Write data/invoices/<token>.pdf and return its path (empty string on failure)."""
    from app.api import server as srv  # imported lazily: the server imports this module
    inv = srv.get_invoice(public_token)
    data = build_pdf(inv)
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "invoices")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{public_token}.pdf")
    with open(path, "wb") as fh:
        fh.write(data)
    return path
