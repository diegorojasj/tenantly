# Tenantly — How it works and how people use it

> Companion to [PRODUCT.md](./PRODUCT.md), which defines *what* the system is. This document
> defines *how it behaves* for the people who use it every day, and the rules the
> frontend follows so it stays easy to understand and hard to misuse.

---

## 1. Who uses it, and for what

A tenant is one business. Inside a tenant, people only ever do one of five jobs. The UI is
built around these jobs, not around features.

| Person | Typical role | Their one question | Lands on | Sees |
|---|---|---|---|---|
| **Front desk** | Front desk lead | “Who's next, and are they ready?” | Today | Operate + Payments |
| **Manager** | Area manager | “Is my area running well, and what should I change?” | Today | Operate, Set up, Money & insight, Policies |
| **Owner / admin** | Owner, Admin | “Is the business healthy, and is it set up right?” | Today | Everything (Plan & usage and Business settings are owner-only) |
| **Analyst** | Analyst | “What are the numbers?” | Insights | Read-only Operate, Catalog, Resources, Payments, Insights |
| **Auditor** | Auditor | “Who changed what?” | Audit trail | Audit trail, Plan & usage |

**Rule: you only see what you can use.** A page appears in the navigation only if the role
can act on it, or needs to read it for its job. Nothing is greyed out “for later”.

These are the roles a business starts with (from its template). A business can rename and
re-scope them, or add its own (“Night desk”, “Franchisee”) on **Team & roles**: pick what the
role can do from the permissions you hold yourself. You can't hand out more than your own
role can do, edit your own role, or touch the Owner role; a role someone holds can't be
removed until they have another.

---

## 2. The words are the tenant's words

The template ([PRODUCT.md §1](./PRODUCT.md)) renames every noun: a gym has *Members* and
*Coaches*, a rental shop has *Renters* and its *Fleet*, a field crew has *Accounts* and *Vans*.
It also names the levels of the location tree: the original templates group locations into
*Areas*; a franchise template might use *Regions* and *Franchisees* above its *Stores*.
Money is shown in the business's own currency.
The UI never shows “customer”, “resource” or “booking” where the tenant uses its own word.
Statuses use the same rule: a rental is *Out* and *Returned*, a visit is *On site* and
*Completed*, but they're the same states underneath.

---

## 3. The everyday journeys

Each journey is designed to finish in as few decisions as possible, and every step says what
happens next.

### 3.1 Run the desk (front desk, many times a day)

1. Open **Today**. The next 3 hours of arrivals are already listed.
2. Press **Check in** on the person in front of you. A confirmation appears at the bottom.
3. If they owe money, or a document the business asks for (a waiver, a vaccination) is
   missing or expired, **Needs attention** says so. One click takes you to the fix: record
   the document on their profile.
4. When the work is done, press **Complete** in *In progress*. The charge is raised for you.

### 3.2 Book someone (front desk, manager)

1. Press **New booking** (Today, Calendar or Bookings).
2. Pick **what**, **who** and **when**. Only times that are actually free are offered: the
   staff member is available, a unit of the right type is free, it's inside opening hours and
   the booking window. If nothing is free, the form says so and suggests changing the day or
   the staff member.
3. If the offering serves a subject (a pet, a vehicle), pick which of theirs; their
   household's or company's count too. Fill in any booking details the template asks for.
4. Press **Book**. If the site requires approval, the booking starts as a *request* and the
   confirmation says so. If a policy makes a document *required to book* and it's missing or
   expired on that day, the booking is refused with what's missing.

Classes and tours are booked by **joining a session**, which shows how many spots are left.

### 3.3 Handle what changed (front desk)

Cancellations, no-shows and refunds are **two-step**: the first press asks “Sure?”, the second
does it. The policy decides the money (no-show fee, refund of paid charges), and the
confirmation message says what happened.

### 3.4 Keep the business set up (owner, manager)

| When the business changes… | Go to | Do |
|---|---|---|
| New service, class or plan | Catalog | Add offering (start from a preset; change its rules if needed) |
| A document becomes compulsory | Policies → Documents | Set it to *Required to book* (or *Remind*) at the right level |
| New staff member or unit | Resources | Add |
| New area, region or franchisee | Locations | Add it at the top, or *… here* inside a group (as deep as the template's levels go) |
| Someone needs a different set of permissions | Team & roles | **New role**, or **Edit** a role you can fully grant |
| Currency, tax, logo or domain | Business settings | Change and save (owner only) |
| Something breaks | Resources | Take out of service (it disappears from new bookings) |
| A rule changes | Policies | Override at the right level: business, area or site |

### 3.5 Get paid (front desk, owner)

**Payments** lists open charges first, oldest debt on top. **Collect** marks one paid.
**Refund** is two-step. *Collected* counts money by the day it arrived.

**Invoice** on an open charge gathers all of that customer's open charges onto one invoice
(`INV-0001`, numbered per business) with the business's tax: shown as the share already in
the price, or added on top, as set in **Business settings**. **Mark paid** collects every
charge on it; **Void** (two-step) puts them back as open charges. A charge on an open invoice
is collected through its invoice.

### 3.6 Know if it's working (owner, analyst)

**Insights** compares a period with the one before: revenue, utilization, returning
customers, no-shows, best offerings, locations side by side. It's about trends; Today is about
now. They never repeat each other.

---

## 4. Rules every screen follows

1. **One primary action per screen**, always top right, always worded with the tenant's noun
   (“New reservation”, “Add member”).
2. **Every page says what it's for** in one plain sentence under the title.
3. **Prevent, don't scold.** Forms only offer valid choices: free times, units of the right
   type, active offerings. The server still checks everything; when it refuses, the message
   says why and what to try instead.
4. **Every action answers.** A short confirmation appears after each change (“Checked in Lena
   Okafor”). Failures stay on screen next to the action.
5. **Irreversible means two steps.** Cancel, no-show, refund, retire, take out of service.
6. **Show the flow.** Lists of bookings show the lifecycle in order, so the states make sense
   on their own.
7. **Nothing is lost by switching.** Scope (business → area → site) lives in the URL and
   follows you across pages; the tenant colour and name frame the screen so you always know
   whose data you're touching.
8. **Empty is a hint, not a blank.** Empty lists say what would appear and how to add it.

---

## 5. What the system guarantees (enforced by the server)

| Guarantee | Why it matters to users |
|---|---|
| Tenants never see each other's data | Trust, compliance |
| Scope limits what a person can see and change | A site lead can't edit another site |
| No resource is double-booked | The calendar is always true |
| Classes never exceed capacity; packs spend credits | No overselling |
| Documents a policy requires are on file and current before booking | Compliance without checking by hand |
| Lifecycle moves only forward along allowed steps | History stays honest |
| Money follows the lifecycle and the policies | Fees and refunds aren't manual |
| Every change is in a tamper-evident audit trail | Disputes have an answer |

---

## 6. Not in this iteration

Real payments, email delivery (invite links are copied by hand), the customer-facing booking
page, sending reminders, and per-resource working hours (each location has its own time
zone and opening hours; set them on **Locations → Hours**). Deposits are a
setting but aren't collected yet. Single sign-on can be configured on **Business settings**
but isn't connected (everyone signs in with email and password), and the custom domain is
recorded, not served. Invoices are records: no PDF, email or partial payments.
