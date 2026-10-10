# Reply to App Review — Submission 637517d1-2a6d-499c-ac8d-0f76a291bf8c

Paste into App Store Connect → Resolution Center. Check the pricing lines against
your own contracts before sending.

---

Thank you for the detailed review. We have addressed all three points below.

## Guideline 2.1 — Information Needed

DH FleetView is a business-to-business fleet management tool. It is used only by
haulage and transport companies that already hold a commercial service agreement
with us. It is not a consumer product and nothing is ever sold through the app.

**Is there any cost for using the tracking platform? If so, how does the user pay?**

The app itself is free and contains no purchases of any kind. The underlying
service is paid for by the operating company — the haulage business — under a
commercial contract signed with us directly. We invoice that company by email and
they pay by bank transfer on standard commercial terms. The person using the app
is an employee of that company, typically a transport manager or a driver, and
never pays anything personally, inside the app or outside it.

**Are users required to purchase and install external hardware?**

The individual app user is not. The operating company is. Vehicle tracking
requires a telematics unit, and in some cases a camera system, physically fitted
to each vehicle. We supply this hardware and our engineers install it in the
vehicle as part of the fleet agreement. A driver or transport manager downloading
the app never purchases hardware themselves.

**What is the price of the device and services?**

Hardware and installation are quoted per fleet, because the specification varies
with the vehicle and the number of cameras required. The ongoing service is
charged per vehicle per month:

- £10 per vehicle per month — live tracking and live view
- £20 per vehicle per month — tachograph compliance, tracking and live view

These are agreed in the contract before any vehicle is fitted.

**Is it a one-time fee or a subscription-based model?**

Both, and both are business-to-business. The hardware and its installation are a
one-off purchase by the operating company. The service above is an ongoing
monthly charge per vehicle, which we invoice quarterly in arrears, by email, for
payment by bank transfer. There is no auto-renewing consumer subscription, and no
payment mechanism of any kind within the app.

**How do users obtain an account?**

We create the accounts. When a transport company signs an agreement with us, we
set up their account and their vehicles, and we issue sign-in details to the
people they nominate. Their transport manager then requests accounts for
individual drivers as needed. There is no way for a member of the public to
obtain an account, and as of this build there is no registration screen in the
app at all (see 3.1.1 below).

**After purchasing the hardware, is a subscription fee required?**

Yes — the monthly per-vehicle service charge described above. It is billed to the
company, not to any individual, and not through Apple.

**What does the subscription fee include?**

- Live vehicle tracking and journey history
- Live and recorded video, for vehicles with cameras fitted
- Automatic tachograph file download and analysis
- Drivers' hours and working time compliance reporting, which UK and EU operators
  are legally required to carry out
- Vehicle defect reporting and maintenance reminders
- Technical support, hosting and software updates

## Guideline 3.1.1 — Business — Payments — In-App Purchase

Understood, and corrected. Account registration has been **removed entirely**.
The sign-up screen and the "Register" link are gone, and the server no longer
accepts self-registration at all. The app is now sign-in only, for people whose
accounts we have already created under their company's agreement. There is no
route from the app to any external purchase, sign-up or payment page.

This matches how the product is actually sold: accounts have always been
provisioned by us as part of a negotiated B2B contract, and the registration
screen was a leftover from the underlying open-source platform we build on. It
should not have been reachable and is now removed.

## Guideline 1.5 — Safety — Support URL

Also corrected. We have published a dedicated support page:

**https://dhfleetview.co.uk/support.html**

It gives a support email address, our hours and response time, what to include
when reporting a problem, and answers to the questions customers actually ask —
including how to obtain an account, what the service costs, and what hardware is
involved. We have updated the Support URL in App Store Connect to point to it.

---

Please let us know if you need anything further, and thank you for your time.
