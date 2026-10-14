"""The business ledger: expenses and other income beside the charges (downtime costs, rent, payouts)."""

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0007_custom_plan_versions_per_business'),
    ]

    operations = [
        migrations.CreateModel(
            name='Entry',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.UUIDField(db_index=True)),
                ('location_id', models.UUIDField()),
                ('kind', models.CharField(choices=[('income', 'Income'), ('expense', 'Expense')], max_length=8)),
                ('category', models.CharField(max_length=40)),
                ('description', models.CharField(max_length=200)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('date', models.DateField()),
                ('source', models.CharField(choices=[('manual', 'Manual'), ('downtime', 'Downtime')], default='manual', max_length=10)),
                ('ref_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('charged', models.BooleanField(default=False)),
                ('recorded_by', models.CharField(blank=True, max_length=160)),
                ('voided', models.BooleanField(default=False)),
                ('key', models.CharField(blank=True, max_length=64, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-date', '-created_at'],
                'indexes': [models.Index(fields=['tenant_id', 'date'], name='billing_ent_tenant__89244b_idx')],
                'constraints': [models.UniqueConstraint(fields=('tenant_id', 'key'), name='one_entry_per_key')],
            },
        ),
    ]
