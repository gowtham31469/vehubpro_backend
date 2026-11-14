from django.db import migrations

# Seeds the three starting labour categories for every existing tenant.
# Tenant-curated from here on (like ServiceCategory) — tenants can rename,
# reorder, add to, or archive these; this migration only gives each tenant
# the same starting point.
SEED_NAMES = ["Periodic Maintenance", "General Repair", "Painting"]


def seed_labour_categories(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    LabourCategory = apps.get_model("services", "LabourCategory")

    for tenant in Tenant.objects.all():
        existing_names = set(
            LabourCategory.objects.filter(tenant=tenant, is_archived=False)
            .values_list("name", flat=True)
        )
        for position, name in enumerate(SEED_NAMES, start=1):
            if name in existing_names:
                continue
            LabourCategory.objects.create(tenant=tenant, name=name, sort_order=position * 10)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0009_labourcategory_serviceitem_labour_category_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_labour_categories, noop_reverse),
    ]
