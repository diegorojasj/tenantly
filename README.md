# Tenantly
## Description
An enterprise-grade multi-tenant SaaS platform serving multiple organizations, and multiple business units within each, from a single deployment. Tenants are logically isolated through tenant-scoped data access and row-level security, with hierarchical structures (organization → region → location) supporting role-based access control, SSO, audit logging, and per-tenant configuration of workflows, fields, pricing rules, and integrations without custom code. Shared services for authentication, billing, notifications, and analytics are centralized, enabling horizontal scaling, uniform security patching, and predictable operating costs as tenant count grows

## Status
Built today: identity (accounts, tenants with currency/tax and branding settings, a location tree of template-named levels at any depth, per-tenant custom roles, audit), operations (catalog, resources, customers, bookings, policies) and billing (charges, customer invoices with tax, usage-based Tenantly subscriptions with their own invoices), with decimal amounts end to end. SSO can be configured but isn't connected; notifications and a separate analytics service are planned, not built. See `docs/` — PRODUCT, ARCHITECTURE, USAGE, PLATFORM and BILLING (the roadmap to a generic core + modules + templates).

## Tenantly admin console
Staff manage business owners, subscriptions, plan prices and the billing policy at **http://admin.localhost:8080** (its own host; the app's host never serves it). Admin accounts are separate from workspace accounts, never deleted, and only usable inside a short access window opened from the server:

```bash
podman compose exec identity python manage.py create_admin you@tenantly.dev --name "You"  # prints the password once, opens 10 minutes
podman compose exec identity python manage.py activate_admin you@tenantly.dev              # new password (printed once) + another 10-minute window
podman compose exec identity python manage.py block_admin you@tenantly.dev                 # close it now
```

Set `ADMIN_JWT_SECRET` (different from `JWT_SECRET`) in `.env`; `ADMIN_WINDOW_MINUTES` and `ADMIN_HOST` are optional. Everything admins do is in the console's append-only admin log. Details: `docs/ARCHITECTURE.md` (Tenantly admin console) and `docs/BILLING.md` §12.
