# Tenantly — Platform direction: core + modules + templates

> Where the generic model goes next. Today: [PRODUCT.md](./PRODUCT.md) (what it is),
> [ARCHITECTURE.md](./ARCHITECTURE.md) (how it runs).

Tenantly runs businesses that sell **time, capacity or access**. To cover more verticals
without custom code, the product becomes three layers:

| Layer | What it is | Changes when |
|---|---|---|
| **Core** | Tenancy, location tree, roles, audit, policies, custom fields, documents, billing, integrations, branding | Rarely; every tenant uses it |
| **Modules** | Capabilities a tenant switches on: Scheduling, Work orders, Memberships, Assets, Invoicing, (later) Inventory | A new kind of work appears |
| **Templates** | Data packs: modules on, vocabulary, fields, statuses, policy defaults, default roles | A new vertical appears |

## Which verticals fit

| Group | Examples | Needs |
|---|---|---|
| A. Time / capacity / access | gyms, clinics, salons, vet, rentals, hotels, coworking, parking, storage, marinas | Scheduling + time model below |
| B. Jobs / tickets / work orders | field service, HVAC, plumbing, ITSM, MSP, facilities, inspections | Work-orders module |
| C. Stock / orders / ledgers | retail, wholesale, warehouse, supply chain, accounting, banking | Inventory/Orders module — **out of scope for now** |
| D. Platform capabilities | franchise, white-label, compliance, workflows, territories, vendor portals | Core features, not templates |

## Gaps to close (in order)

1. ~~**Template registry.**~~ **Done:** templates are stored, versioned `Template` rows in
   identity (seeded with the original three); ids are strings end to end; other services read
   the template's rules from the tenant token. Still open: tenants overriding wording and
   fields.
2. **Time model.** **Mostly done:** each location has an IANA time zone (default UTC)
   and optional opening hours overriding the template's, set on the Locations page and
   carried in the token's node rows. Bookings are stored as aware UTC; slots, hours, "today"
   and the wire's wall-clock strings use the location's zone. Rentals can be priced by the
   hour (one day, 8 h cap, as before), day, night or month; the last three book whole
   local days (or months) and are priced by length. Still open: **per-resource working
   hours** (staff/asset availability is only "not already booked"), hours that differ by
   weekday or date (holidays), check-in/check-out times distinct from opening hours, and a
   per-template step other than 30 minutes.
3. ~~**Fulfilment rules instead of five kinds.**~~ **Done:** every offering carries its own
   rules: capacity (1 books a slot per customer, N makes a session customers join), time
   (`slot` fixed length · `window` by the hour on one day · `span` whole days / nights /
   months · `none` for plans), place (`on_site` / `at_customer`) and a requirement list.
   Operations branches on those rules only; `kind` just names the template **preset** the
   offering started from (`Template.presets`: the five old kinds, now data, with their
   rules as defaults the catalog form can override, e.g. a three-seat "appointment").
   Existing offerings were migrated to the rules they used to imply. Still open: place is
   informational (no travel time or address checks), and sessions are still fixed-length.
4. ~~**Resources.**~~ **Done:** templates define resource types (`Template.resourceTypes`:
   key, labels, `people`, the category label and **typed attributes** — text, number, bool,
   choice, optional/required). An offering's `requires` lists `{type, quantity, pick, role,
   where}`: the desk picks the `pick` ones (a dentist), the rest are assigned free (a chair
   with `xray: true`, two hygienists), all checked and locked together. Resources may
   **nest** inside another at the same location (property → unit): booking either blocks
   the other. The original templates keep their `staff` / `asset` types, so fitness,
   rentals and field book exactly as before. Still open: editing templates' types and
   presets from the UI, per-tenant overrides, attribute ranges (only equality filters),
   and requirement choice by the customer (e.g. "any dentist").
5. ~~**Parties.**~~ **Done:** templates define **account types** (`Template.accountTypes`:
   a company, a household, with their own typed fields) and **subject types**
   (`Template.subjectTypes`: pet, child, vehicle, property, with typed fields). In
   operations a customer may belong to one `Account` (with a free-text role: Billing
   contact, Parent) whose members are its contacts; a `Subject` belongs to a customer or to
   an account (the household's dog, the company's site) and every contact can bring it in.
   An offering may name a `subjectType` (default: its preset's `subject`); each booking of
   it then names one of the customer's subjects of that type. Plans are `Subscription` rows,
   so a customer holds several: a class seat is covered by a current monthly plan first,
   else the oldest pack with credits (the seat remembers which, so a cancelled class refunds
   that pack), else it's a paid drop-in; selling a plan they already hold renews or tops it
   up. Existing plans became one subscription each (reversibly). Still open: moving a
   customer between accounts and editing subjects from the UI, billing an account instead
   of a person, subscriptions held by an account, renewals and proration.
6. ~~**Typed custom fields and documents.**~~ **Done:** `Template.fields` holds typed
   definitions per entity (`customer`, `account`, `offering`, `booking`; subject types and
   resource types carry theirs): `{key, label, type: text|number|bool|choice|date, options,
   required, pii, expires}`, validated by one module (`services/fields.py`). `pii` values
   are only shown to roles with `bookings.manage`; an `expires` date is reported as expired
   once past. `Template.documents` lists document types (`{key, label, appliesTo:
   customer|subject, subjectType, validDays}`); a `Document` is recorded for a customer or one
   of their subjects with an issue date and an expiry (default `validDays`). Each type gets a
   `docs.require.<key>` policy, inherited down the tree: *Not needed*, *Remind* (flagged on
   the profile and in Today's arrivals, what the waiver flag did) or *Required to book*
   (booking and joining a session are refused unless one is valid on the day; subject
   documents are checked against the booking's subject). The waiver flag became a "waiver"
   document type, `docs.waiver: true` became *Remind*, and signed waivers became documents,
   all reversibly, so fitness and rentals behave as before and field service asks for
   nothing. Still open: editing templates' fields and documents from the UI, file uploads
   (a document is a record, not a scan), expired-field enforcement at booking, and PII
   masking in the audit trail and exports.
7. ~~**Lifecycle as data.**~~ **Done:** each template carries its state machine
   (`transitions`), served with the tenant and enforced by operations from the token; the
   duplicated tables in `bookings.py` and `lifecycle.ts` are gone.
8. ~~**Tree depth and roles.**~~ **Done:** templates name the tree's group levels
   (`Template.levels`: `{key, label, plural}`, top to bottom: an area; or region →
   franchisee), and a group node (`kind: region`) records its `level`. A group goes under the
   business or a group on a higher level (levels may be skipped); locations go under either;
   the tree is as deep as the template's levels. Scope, policies and the token work at any
   depth unchanged. Roles are per business: `Template.roles` lists the defaults, copied into
   `Role` rows when a business is created; Team & roles adds, edits and removes them. Nobody
   creates, edits or removes a role that can do something their own role can't, or edits the
   role they hold; `owner` is fixed and always holds every permission; a role someone holds
   can't be removed. Existing templates got one "Area" level and the six platform roles,
   existing groups that level and every business its own copy of the roles, all reversibly,
   so fitness, rentals and field look and behave as before. Still open: editing a template's
   levels and default roles from the UI, moving a node to another parent or level, and
   scoping a custom role to particular levels.
9. ~~**Money.**~~ **Done:** each business has a currency (ISO 4217, default USD), a tax rate,
   a tax name and whether prices include tax (identity's `Tenant`, carried in the tenant
   token's `money` claim). Amounts are `Decimal` in every service and decimal strings on the
   wire (`"12.50"`); the frontend adds them on integer cents and formats them in the
   business's currency. Charges snapshot their currency. Billing issues simple customer
   invoices: a customer's open charges under a sequential number (`INV-0001`), with tax
   added on top or shown as the share already inside prices; paying one collects its charges,
   voiding it releases them. Tenantly's own plan prices and limits moved from the frontend
   into billing (`services/plans.py`, `GET /plan`, seats read from identity). Existing charges
   became USD, reversibly; with tax at 0 % nothing changes for fitness, rentals or field.
   Still open: currencies whose minor unit isn't two decimals, several tax rates (per
   offering or location), credit notes and partial payments, invoice PDFs and numbering
   formats, and invoicing an account instead of a person.
10. ~~**Branding.**~~ **Done (placeholder SSO):** a business can set a logo URL (https, shown
    in the workspace shell), a custom domain (validated and unique across businesses) and
    single sign-on settings (SAML metadata URL or OpenID Connect issuer and client ID) on
    **Business settings** (`tenant.manage`); changes are audited. SSO is stored only:
    nothing contacts an identity provider, it is never enforced, and sign-in stays email and
    password. Still open: real SSO (SAML/OIDC login, just-in-time members, enforcing it),
    serving the workspace on the custom domain (TLS and routing), theme colours beyond the
    hue, and branded emails.

Each step ships behind the current three templates first, so nothing regresses before new
templates are added.
