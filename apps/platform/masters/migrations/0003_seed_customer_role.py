from django.db import migrations

# Distinct from the internal staff hierarchy (SUPER_ADMIN/ADMIN/MANAGER/STAFF)
# — this is the role assigned to a User account created for an end customer
# signing up (see Customer.user link). Deliberately excluded from
# RoleListAPIView (masters/views.py), which only offers roles assignable to
# tenant staff.
CUSTOMER_ROLE = ("CUSTOMER", "Customer")


def seed_customer_role(apps, schema_editor):
    Role = apps.get_model("masters", "Role")
    code, name = CUSTOMER_ROLE
    Role.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})


def remove_customer_role(apps, schema_editor):
    Role = apps.get_model("masters", "Role")
    Role.objects.filter(code=CUSTOMER_ROLE[0]).delete()


class Migration(migrations.Migration):
    dependencies = [("masters", "0002_move_state_city_models")]
    operations = [migrations.RunPython(seed_customer_role, remove_customer_role)]
