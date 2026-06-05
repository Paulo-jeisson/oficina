from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0005_multi_tenancy_oficina'),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS unique_codigo_estoque_por_oficina',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name='estoqueitem',
            constraint=models.UniqueConstraint(
                condition=models.Q(('codigo__gt', '')),
                fields=('oficina', 'codigo'),
                name='unique_codigo_estoque_por_oficina',
            ),
        ),
    ]
