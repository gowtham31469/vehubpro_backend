# Generated migration for adding signature and recommendation fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0004_alter_invoice_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='next_service_recommendation',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='invoice',
            name='customer_signature',
            field=models.TextField(blank=True, help_text='Base64-encoded customer signature image', null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='customer_signature_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='admin_signature',
            field=models.TextField(blank=True, help_text='Base64-encoded admin/owner signature image', null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='admin_signature_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
