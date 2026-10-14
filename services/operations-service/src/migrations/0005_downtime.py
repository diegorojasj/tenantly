"""Downtime: windows when a resource, an offering or a whole location can't be booked."""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0004_parties_fields_documents'),
    ]

    operations = [
        migrations.CreateModel(
            name='Downtime',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.UUIDField(db_index=True)),
                ('location_id', models.UUIDField(db_index=True)),
                ('reason', models.CharField(choices=[('maintenance', 'Maintenance'), ('repair', 'Repair'), ('unfit', 'Unsuitable for use'), ('absence', 'Absence'), ('closure', 'Closure'), ('other', 'Other')], max_length=12)),
                ('note', models.CharField(blank=True, max_length=300)),
                ('start', models.DateTimeField()),
                ('end', models.DateTimeField(blank=True, null=True)),
                ('recorded_by', models.CharField(blank=True, max_length=160)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('offering', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='downtimes', to='operations.offering')),
                ('resource', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='downtimes', to='operations.resource')),
            ],
            options={
                'ordering': ['start'],
                'indexes': [models.Index(fields=['tenant_id', 'location_id', 'start'], name='operations__tenant__51ef4d_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('resource__isnull', True), ('offering__isnull', True), _connector='OR'), name='downtime_one_target'), models.CheckConstraint(condition=models.Q(('end__isnull', True), ('end__gt', models.F('start')), _connector='OR'), name='downtime_ends_after_start')],
            },
        ),
    ]
