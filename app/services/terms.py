"""Terms & Conditions — the owner's own document, verbatim structure.

The signed document is versioned and hashed: whatever the client agreed to on a
given date can be reprinted byte-for-byte. Bump TERMS_VERSION whenever the text
changes (never edit an existing version in place).

Placeholders the owner left in the draft are filled from data/services.json
(bracketed values in the source are shown as the shop's real settings).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app import db as dbmod
from app.services import pricing

TERMS_VERSION = "2026.03"

TERMS_MD = """# Bimmer House Calls: Terms and Conditions of Service

**Effective date: {effective_date}**

## 1. About These Terms
These Terms and Conditions (the "Terms") apply to all services provided by Bimmer House Calls ("we," "us," or "the Company"), a mobile automotive service business located by the Jersey Shore, New Jersey. By booking, paying a deposit, or allowing us to begin work, you ("the Customer") agree to these Terms.

Contact: {phone}, {email}

## 2. Services
We provide mobile maintenance, repairs, performance part installation, ECU unlocking and tuning, cosmetic modifications, and related services for BMW vehicles at the Customer's home, workplace, or other agreed location. The services offered, descriptions, and starting prices are listed on our website and may change at any time.

## 3. Quotes, Estimates, and VIN
- A Vehicle Identification Number (VIN) is required for every quote and booking so we can confirm your exact model, engine, options, and which parts and tunes fit your vehicle.
- Prices shown on our website are for labor only. They are starting points and depend on your vehicle, the condition of the parts, and the work needed.
- You supply the parts for every job. We do not order, source, stock, or mark up parts unless we agree otherwise in writing before the appointment.
- We will provide a quote before work begins. A quote is valid for {quote_valid_days} days unless stated otherwise.
- Quotes are estimates based on what we can see before work starts. If we discover a problem that changes the work needed, we will contact you and get your approval before doing anything that raises the price.

## 4. Scheduling and Service Location
- Appointments are scheduled based on availability and your service area. Our service hours are {hours_label}.
- You agree to provide a safe, reasonably level, accessible space to work (such as a driveway or garage) with adequate room around the vehicle. We may reschedule or decline work if the location is unsafe or unsuitable.
- Because we work outdoors in many cases, we may reschedule due to rain, snow, extreme temperatures, or other unsafe weather.
- You or an authorized adult must be available at the start of the appointment and must provide access to the vehicle and its keys.
- If we arrive and cannot start the job within {late_start_minutes} minutes because the vehicle, keys, or location is unavailable, we may treat the appointment as a late cancellation.

## 5. Travel Fees
A travel fee may apply based on the driving distance between our starting point and your service address. The fee is shown during booking or in your quote, and it is separate from the service price. We may decline bookings outside our service area.

## 6. Payment
- A deposit may be required to confirm your booking. The deposit is applied toward your final total. Standard menu services do not require a deposit; custom builds require a deposit before the appointment is held.
- The remaining balance is due when the work is completed, before the vehicle is released, unless we agree otherwise in writing.
- We accept {accepts}. Online payments are processed through our payment provider.
- Parts that we order for you (including special-order parts) require payment or a deposit before ordering. Special-order and electrical parts are non-refundable once ordered unless they arrive defective or incorrect.
- Unpaid balances may be subject to a late fee of {late_fee_percent}% per month and collection costs where permitted by law.
- Returned or declined payments may incur the processor's fee.

## 7. Cancellations and Rescheduling
- You may cancel or reschedule free of charge with at least {cancel_hours} hours' notice.
- Cancellations with less than {cancel_hours} hours' notice, no-shows, or being unavailable when we arrive may result in forfeiture of your deposit and/or a fee equal to the travel fee for that visit.
- If we need to cancel or reschedule, we will contact you as soon as we can and offer a new time or a refund of your deposit.

## 8. Customer Responsibilities
You agree to:
- Provide accurate information about yourself and your vehicle, including the VIN and any known problems, modifications, previous tuning, or warning lights.
- Confirm that you are the owner of the vehicle or have the owner's authority to approve the work.
- Remove valuables and personal items from the vehicle. We are not responsible for items left inside.
- Disclose any known safety issues, accident damage, prior repairs, or aftermarket modifications.
- Keep children and pets away from the work area.

## 9. Parts
- We may supply parts or install parts that you provide.
- Parts we supply carry the manufacturer's or supplier's warranty, if any. We are not the manufacturer and make no promise beyond what the manufacturer offers.
- Customer-supplied parts are installed at the Customer's risk. We do not warranty the parts themselves, their fit, or their performance. If a customer-supplied part is incorrect, defective, or fails during or after installation, you are responsible for the cost of any additional labor, including removal, reinstallation, or a repeat visit.
- We reserve the right to decline to install any part we believe is unsafe, incorrect, or poor quality.

## 10. Additional Work and Unexpected Issues
BMW vehicles can hide problems that only appear once work begins, such as worn, brittle, seized, or corroded components. If we find additional issues, we will tell you and give you the option to approve extra work or stop. We will not perform additional work that raises the price without your approval. You are responsible for payment for all approved work and for the time spent on work that was started and then stopped.

## 11. Performance Modifications, ECU Unlocking, and Tuning
Performance modifications and tuning involve real risks. By booking these services you acknowledge and agree that:
- **Warranty.** Modifications and tuning may void or reduce your manufacturer warranty, extended warranty, or other coverage, and a dealer or warranty provider may deny claims related to your vehicle. We do not guarantee warranty coverage.
- **Wear and failure risk.** Increased power and different tuning can increase stress and wear on the engine, transmission, drivetrain, and other components, and can lead to part failure, even when the work is done correctly.
- **ECU unlocking risk.** Unlocking an ECU involves removing it from the vehicle and working on it directly. There is a risk of damaging or permanently disabling the ECU, which could require repair or replacement at the Customer's cost. We do not guarantee that every ECU can be successfully unlocked.
- **No guaranteed results.** Power, torque, speed, fuel economy, and sound results vary by vehicle, fuel quality, condition, and conditions. We do not promise specific numbers.
- **Third-party software.** Tunes are provided by third-party tuning companies and may require a separate license. Their terms, licensing fees, and support policies apply. We are not responsible for the software itself, license problems, or software updates that affect your tune.
- **Return to stock.** Returning your vehicle to its original software or parts may not be possible, may not hide prior modifications, and may cost extra.
- **Maintenance.** Modified vehicles may need more frequent maintenance. You are responsible for keeping up with proper maintenance, quality fuel, and safe operation.
- **Track and unsafe use.** We do not recommend reckless, illegal, or unsafe driving. You are responsible for how you drive.

## 12. Legal Compliance
You are responsible for making sure that any part, tune, or modification installed on your vehicle is legal to use where you live and drive, including state and federal emissions, noise, equipment, lighting, and inspection laws. Rules vary by state and by vehicle, and some modifications may not be legal for use on public roads. We are not responsible for fines, failed inspections, registration issues, or insurance problems resulting from modifications. Check with your insurance provider before modifying your vehicle, since some policies do not cover modified cars.

## 13. Cosmetic Modifications and Interior Work
Cosmetic installs (grilles, mirror caps, lips, lighting, badges, headliner and starlight work, and similar) may involve removing trim, panels, clips, and the headliner. On older vehicles, plastic clips, trim, headliner material, and adhesives can be brittle or worn and may break or show damage during removal even with careful handling. We are not responsible for pre-existing wear or damage, or for normal breakage of aged parts. We will tell you about this risk when we see it, and we may recommend replacement parts at your cost.

## 14. Limited Workmanship Warranty
- We warranty our workmanship for {labor_warranty_days} days from the date of service, covering defects in the labor we performed.
- The warranty does not cover parts (see Section 9), customer-supplied parts, normal wear, damage from accidents, misuse, racing, neglect, further modifications, or unrelated problems, and it does not cover issues related to tuning or modifications beyond our workmanship.
- To make a claim, contact us promptly at the number or email above. We may inspect the vehicle and will repair or redo the affected work at our discretion. This is your only remedy under the warranty.
- A travel fee may apply to warranty visits.

## 15. Limitation of Liability
To the fullest extent allowed by law:
- We are not liable for indirect, incidental, consequential, or special damages, including loss of use of the vehicle, towing, rental cars, lost income, or inconvenience.
- Our total liability for any claim related to our services is limited to the amount you paid us for the specific service that caused the claim.
- We are not responsible for damage caused by pre-existing conditions, hidden defects, previous repairs, or the failure of parts that were already worn.

Nothing in these Terms limits any rights you have under New Jersey or federal consumer protection laws that cannot be waived.

## 16. Indemnification
You agree to be responsible for, and to hold us harmless from, claims, damages, and costs arising from inaccurate information you provide, your use of the vehicle after service, your failure to follow safety or maintenance recommendations, or your breach of these Terms, to the extent permitted by law.

## 17. Right to Refuse or Stop Service
We may decline or stop work if we believe the work is unsafe, the location is unsuitable, the vehicle has serious safety issues, payment has not been made, or a customer is abusive, threatening, or dishonest. You will be responsible for payment for work already performed and for parts already ordered.

## 18. Photos, Video, and Social Media
We may take photos and videos of work performed for documentation and for use on our website and social media. We will not show your name, license plate, VIN, or address. If you do not want your vehicle shown, tell us before the appointment and we will respect your request.

## 19. Privacy and Communications
- We collect your name, phone number, email, address, vehicle information, and VIN to provide and schedule services, and we do not sell your personal information.
- By booking, you agree that we may contact you by phone, text, or email about your appointment, quote, payment, and service.
- Newsletter and promotional messages are sent only if you opt in, and you can unsubscribe at any time using the link in the message or by contacting us.
- Payments are processed by third-party providers. We do not store full card numbers.

## 20. Disputes and Governing Law
These Terms are governed by the laws of the State of New Jersey. If a problem arises, please contact us first and give us a chance to fix it. Any dispute that cannot be resolved informally will be handled in the courts of {county}, New Jersey, or through small claims court.

## 21. Changes to These Terms
We may update these Terms from time to time. The version in effect on the date of your booking applies to your service.

## 22. Entire Agreement
These Terms, together with your quote or booking confirmation, are the entire agreement between you and Bimmer House Calls for the service. If any part of these Terms is found unenforceable, the remaining parts stay in effect.

## Customer Acknowledgment and Waiver
By signing electronically and checking the box below, I confirm that:
- I have read and agree to these Terms and Conditions.
- The vehicle information I provided, including the VIN, is accurate, and I am the owner or authorized to approve this work.
- I understand that performance modifications, ECU unlocking, and tuning carry risks, may affect my warranty, and can lead to damage or part failure, and I accept those risks.
- I am responsible for ensuring the work and modifications are legal where I live and drive.
- I agree that my electronic signature, together with the timestamp, IP address, and document hash recorded by this system, is a valid and binding signature.
"""

ACK_ITEMS = [
    "I have read and agree to these Terms and Conditions.",
    "The vehicle information I provided, including the VIN, is accurate, and I am the owner or authorized to approve this work.",
    "I understand that performance modifications, ECU unlocking, and tuning carry risks, may affect my warranty, and can lead to damage or part failure, and I accept those risks.",
    "I am responsible for ensuring the work and modifications are legal where I live and drive.",
]


def render_terms(catalog: dict) -> str:
    s = catalog["shop"]
    return TERMS_MD.format(
        effective_date=s.get("termsEffectiveDate", "2026-01-01"),
        phone=s["phone"], email=s["email"],
        quote_valid_days=s.get("quoteValidDays", 7),
        hours_label=s.get("hoursLabel", "Mon–Thu 7am–5pm · Fri–Sat 6am–3pm"),
        late_start_minutes=15,
        accepts=", ".join(s.get("accepts") or ["credit and debit cards", "cash", "Zelle"]),
        late_fee_percent=s.get("lateFeePercent", 1.5),
        cancel_hours=s.get("cancelHours", 24),
        labor_warranty_days=s.get("laborWarrantyDays", 30),
        county=s.get("termsContactCounty", "Ocean County"),
    )


def install_templates(conn, catalog: dict) -> dict:
    body = render_terms(catalog)
    sha = hashlib.sha256(body.encode()).hexdigest()
    conn.execute(
        "INSERT OR IGNORE INTO templates(kind, slug, version, body, sha256) VALUES ('terms','service_agreement',?,?,?)",
        (TERMS_VERSION, body, sha))
    return {"version": TERMS_VERSION, "sha256": sha}


def active_terms(conn) -> dict:
    row = conn.execute("SELECT * FROM templates WHERE kind='terms' AND active=1 ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else {}


if __name__ == "__main__":
    dbmod.init()
    cat = pricing.load_catalog()
    with dbmod.db() as conn:
        print(json.dumps(install_templates(conn, cat), indent=2))
        print(active_terms(conn)["version"])
