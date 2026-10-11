"""Gaps 5-6: parties (accounts, subjects, several subscriptions) and documents instead of the waiver flag.

- Each customer's single plan (`plan_offering`, `plan_renews`, `plan_credits`) becomes one
  active `Subscription`; class seats taken by a pack holder point at that subscription, so
  calling the session off still returns the credit to the same pack.
- Each `waiver_signed` customer gets a "waiver" `Document` (issued the day they became a
  customer, never expiring): the document type identity's 0007 gives the waiver flag.
- `docs.waiver` policy overrides (bool) become `docs.require.waiver`: True -> "Remind",
  which is what the flag did, False -> "Not needed".

Backwards, the first active subscription goes back on the customer and a waiver document
sets `waiver_signed` again.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

OFF, REMIND = "Not needed", "Remind"


def forward(apps, schema_editor):
    Customer = apps.get_model("operations", "Customer")
    Subscription = apps.get_model("operations", "Subscription")
    Document = apps.get_model("operations", "Document")
    Attendance = apps.get_model("operations", "Attendance")
    PolicyOverride = apps.get_model("operations", "PolicyOverride")
    for c in Customer.objects.exclude(plan_offering=None):
        sub = Subscription.objects.create(
            tenant_id=c.tenant_id,
            customer=c,
            offering_id=c.plan_offering_id,
            started=c.since,
            renews=c.plan_renews,
            credits=c.plan_credits,
        )
        if c.plan_offering.unit == "pack":
            Attendance.objects.filter(customer=c).update(subscription=sub)
    for c in Customer.objects.filter(waiver_signed=True):
        Document.objects.create(tenant_id=c.tenant_id, customer=c, type="waiver", issued=c.since)
    for o in PolicyOverride.objects.filter(key="docs.waiver"):
        o.key, o.value = "docs.require.waiver", REMIND if o.value is True else OFF
        o.save(update_fields=["key", "value"])


def backward(apps, schema_editor):
    Customer = apps.get_model("operations", "Customer")
    Subscription = apps.get_model("operations", "Subscription")
    Document = apps.get_model("operations", "Document")
    PolicyOverride = apps.get_model("operations", "PolicyOverride")
    for sub in Subscription.objects.filter(status="active").order_by("-created_at"):
        # Oldest last, so a customer with several keeps the first one they bought.
        Customer.objects.filter(id=sub.customer_id).update(
            plan_offering_id=sub.offering_id, plan_renews=sub.renews, plan_credits=sub.credits
        )
    signed = Document.objects.filter(type="waiver", subject=None).values("customer_id")
    Customer.objects.filter(id__in=signed).update(waiver_signed=True)
    for o in PolicyOverride.objects.filter(key="docs.require.waiver"):
        o.key, o.value = "docs.waiver", o.value != OFF
        o.save(update_fields=["key", "value"])


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0003_fulfilment_rules_resource_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(db_index=True)),
                ("location_id", models.UUIDField(db_index=True)),
                ("type", models.CharField(max_length=30)),
                ("name", models.CharField(max_length=160)),
                ("fields", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="booking",
            name="fields",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="customer",
            name="account_role",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="offering",
            name="fields",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="offering",
            name="subject_type",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="customer",
            name="account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contacts",
                to="operations.account",
            ),
        ),
        migrations.CreateModel(
            name="Subject",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(db_index=True)),
                ("location_id", models.UUIDField(db_index=True)),
                ("type", models.CharField(max_length=30)),
                ("name", models.CharField(max_length=160)),
                ("fields", models.JSONField(default=dict)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subjects",
                        to="operations.account",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subjects",
                        to="operations.customer",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(db_index=True)),
                ("type", models.CharField(max_length=30)),
                ("issued", models.DateField()),
                ("expires", models.DateField(blank=True, null=True)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("recorded_by", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="operations.customer"
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="operations.subject",
                    ),
                ),
            ],
            options={
                "ordering": ["-issued", "-created_at"],
            },
        ),
        migrations.AddField(
            model_name="booking",
            name="subject",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bookings",
                to="operations.subject",
            ),
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(db_index=True)),
                ("started", models.DateField()),
                ("renews", models.DateField(blank=True, null=True)),
                ("credits", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("cancelled", "Cancelled")], default="active", max_length=10
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscriptions",
                        to="operations.customer",
                    ),
                ),
                (
                    "offering",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subscriptions",
                        to="operations.offering",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddField(
            model_name="attendance",
            name="subscription",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="seats",
                to="operations.subscription",
            ),
        ),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(
            model_name="customer",
            name="plan_credits",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="plan_offering",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="plan_renews",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="waiver_signed",
        ),
    ]
