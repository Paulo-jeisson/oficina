# Generated manually for multi-tenancy support.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_default_oficina(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(app_label, model_name)
    Oficina = apps.get_model('agenda', 'Oficina')

    owner = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if owner is None:
        owner = User.objects.create(
            username='admin_oficina',
            is_staff=True,
            is_superuser=True,
        )

    oficina, _ = Oficina.objects.get_or_create(
        dono=owner,
        defaults={'nome': 'Oficina Principal'},
    )

    for model_name in ['Booking', 'OrdemServico']:
        model = apps.get_model('agenda', model_name)
        model.objects.filter(oficina__isnull=True).update(oficina=oficina)

    for model_name in ['OrdemServicoServiceItem', 'OrdemServicoPartItem', 'FinancialTransaction', 'CashFlowRecord', 'FinanceAudit', 'OrdemServicoStatusHistory']:
        model = apps.get_model('agenda', model_name)
        for item in model.objects.filter(oficina__isnull=True).select_related('ordem_servico'):
            item.oficina_id = item.ordem_servico.oficina_id if item.ordem_servico_id else oficina.id
            item.save(update_fields=['oficina'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('agenda', '0004_ordemservico_completed_at_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Oficina',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=120, verbose_name='Nome da oficina')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('dono', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='oficina', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Oficina',
                'verbose_name_plural': 'Oficinas',
                'ordering': ['nome'],
            },
        ),
        migrations.AddField(
            model_name='booking',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='ordemservico',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='ordemservicoserviceitem',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='ordemservicopartitem',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='cashflowrecord',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='financeaudit',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AddField(
            model_name='ordemservicostatushistory',
            name='oficina',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.RunPython(create_default_oficina, noop_reverse),
        migrations.AlterField(
            model_name='booking',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='ordemservico',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='ordemservicoserviceitem',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='ordemservicopartitem',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='financialtransaction',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='cashflowrecord',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='financeaudit',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.AlterField(
            model_name='ordemservicostatushistory',
            name='oficina',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina'),
        ),
        migrations.CreateModel(
            name='EstoqueItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=180, verbose_name='Nome do item')),
                ('codigo', models.CharField(blank=True, max_length=60, verbose_name='Codigo')),
                ('quantidade', models.PositiveIntegerField(default=0, verbose_name='Quantidade')),
                ('custo_unitario', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Custo unitario')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('oficina', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='agenda.oficina', verbose_name='Oficina')),
            ],
            options={
                'verbose_name': 'Item de estoque',
                'verbose_name_plural': 'Itens de estoque',
                'ordering': ['nome'],
            },
        ),
        migrations.AddConstraint(
            model_name='estoqueitem',
            constraint=models.UniqueConstraint(condition=models.Q(('codigo__gt', '')), fields=('oficina', 'codigo'), name='unique_codigo_estoque_por_oficina'),
        ),
    ]
