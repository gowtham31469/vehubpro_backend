"""Add pdf_key to Invoice — stores the relative LOCAL path or S3 object key for the generated PDF."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0002_remove_invoice_payment_mode_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="pdf_key",
            field=models.CharField(
                blank=True,
                help_text="Relative path (LOCAL) or S3 object key for the generated invoice PDF.",
                max_length=512,
                null=True,
            ),
        ),
    ]
