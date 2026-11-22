from django.db import migrations

# Seeds the starting reason categories (the previous fixed enum's options)
# for every existing tenant. Tenant-curated from here on (like
# services.LabourCategory) — tenants can rename, reorder, add to, or archive
# these; this migration only gives each tenant the same starting point.
SEED_NAMES = [
    "Pricing Error", "Product Return", "Service Issue", "Goodwill", "Duplicate Billing", "Other",
]


def seed_reason_categories(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    CreditNoteReasonCategory = apps.get_model("credit_notes", "CreditNoteReasonCategory")

    for tenant in Tenant.objects.all():
        existing_names = set(
            CreditNoteReasonCategory.objects.filter(tenant=tenant, is_archived=False)
            .values_list("name", flat=True)
        )
        for position, name in enumerate(SEED_NAMES, start=1):
            if name in existing_names:
                continue
            CreditNoteReasonCategory.objects.create(tenant=tenant, name=name, sort_order=position * 10)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("credit_notes", "0002_alter_creditnote_reason_category_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_reason_categories, noop_reverse),
    ]
