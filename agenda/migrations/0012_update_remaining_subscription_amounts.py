from decimal import Decimal

from django.db import migrations


def update_remaining_subscription_amounts(apps, schema_editor):
    Assinatura = apps.get_model('agenda', 'Assinatura')
    Assinatura.objects.filter(monthly_amount=Decimal('150.00')).update(monthly_amount=Decimal('99.90'))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0011_alter_assinatura_monthly_amount_and_more'),
    ]

    operations = [
        migrations.RunPython(update_remaining_subscription_amounts, noop_reverse),
    ]
