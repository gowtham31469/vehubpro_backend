from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion
import uuid


def backfill_tenant_domain(apps, schema_editor):
    tenant_model = apps.get_model("tenants", "Tenant")
    for tenant in tenant_model.objects.all().iterator():
        if not tenant.domain:
            tenant.domain = f"tenant-{tenant.id}.local"
            tenant.save(update_fields=["domain"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tenant",
            name="domain",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="onboarded_at",
            field=models.DateTimeField(default=timezone.now, editable=False),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="tenant",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("suspended", "Suspended"), ("cancelled", "Cancelled")],
                default="active",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_tenant_domain, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tenant",
            name="domain",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RemoveField(
            model_name="tenant",
            name="code",
        ),
        migrations.CreateModel(
            name="TenantBranding",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("logo", models.ImageField(blank=True, null=True, upload_to="tenant_logos/")),
                ("dark_logo", models.ImageField(blank=True, null=True, upload_to="tenant_logos/dark/")),
                ("favicon", models.ImageField(blank=True, null=True, upload_to="tenant_favicons/")),
                ("primary_color", models.CharField(blank=True, max_length=20, null=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="branding",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "tenant_branding"},
        ),
        migrations.CreateModel(
            name="TenantPII",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("gstin_encrypted", models.TextField(blank=True, null=True)),
                ("gstin_key_version", models.CharField(blank=True, default="", max_length=16)),
                ("gstin_hash", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("address", models.TextField(blank=True, null=True)),
                ("contact_name_encrypted", models.TextField(blank=True, null=True)),
                ("contact_name_key_version", models.CharField(blank=True, default="", max_length=16)),
                ("email_encrypted", models.TextField(blank=True, null=True)),
                ("email_key_version", models.CharField(blank=True, default="", max_length=16)),
                ("phone_encrypted", models.TextField(blank=True, null=True)),
                ("phone_key_version", models.CharField(blank=True, default="", max_length=16)),
                ("is_anonymized", models.BooleanField(default=False)),
                ("anonymized_at", models.DateTimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pii",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "tenant_pii"},
        ),
    ]
