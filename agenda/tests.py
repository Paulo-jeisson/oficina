from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.db import IntegrityError, transaction
from django.urls import reverse

from datetime import date, time

from .models import (
    Booking, EstoqueItem, EstoqueMovimentacao, Oficina,
    OrdemServico, OrdemServicoPartItem,
)
from .stock import move_stock, reconcile_order_part, reverse_order_part
from .templatetags.agenda_format import brl


class StockTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('oficina1', password='test', is_staff=True)
        self.other_user = User.objects.create_user('oficina2', password='test', is_staff=True)
        self.oficina = Oficina.objects.create(nome='Oficina 1', dono=self.user)
        self.other = Oficina.objects.create(nome='Oficina 2', dono=self.other_user)
        self.item = EstoqueItem.objects.create(
            oficina=self.oficina, nome='Pastilha', codigo='PAS-1', quantidade=10,
            estoque_minimo=3, custo_unitario=Decimal('20'), preco_venda=Decimal('35'),
        )

    def create_order(self):
        booking = Booking.objects.create(
            oficina=self.oficina, full_name='Cliente', phone='11999999999',
            vehicle_brand='Fiat', vehicle_model='Uno', vehicle_year=2020,
            problem_description='Freios', service_type='custom', duration_minutes=30,
            scheduled_date=date.today(), start_time=time(8), assigned_box=1,
        )
        return OrdemServico.objects.create(
            oficina=self.oficina, booking=booking, client_name='Cliente',
            phone=booking.phone, vehicle_brand='Fiat', vehicle_model='Uno',
            vehicle_year=2020, problem_description='Freios', duration_minutes=30,
            scheduled_date=date.today(),
        )

    def test_entry_exit_and_audit(self):
        move_stock(item=self.item, movement_type='entry', quantity=5, user=self.user)
        move_stock(item=self.item, movement_type='exit', quantity=2, user=self.user, note='Avaria')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 13)
        self.assertEqual(EstoqueMovimentacao.objects.filter(oficina=self.oficina).count(), 2)

    def test_negative_stock_is_rejected_atomically(self):
        with self.assertRaises(ValidationError):
            move_stock(item=self.item, movement_type='exit', quantity=11, note='Perda')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 10)
        self.assertFalse(EstoqueMovimentacao.objects.exists())

    def test_adjustment_and_financial_calculations(self):
        move_stock(item=self.item, movement_type='adjustment', target_quantity=2)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 2)
        self.assertEqual(self.item.reposicao_sugerida, 1)
        self.assertEqual(self.item.valor_estoque, Decimal('40'))
        self.assertEqual(self.item.margem_bruta, Decimal('15'))

    def test_tenant_isolation_in_views(self):
        foreign = EstoqueItem.objects.create(
            oficina=self.other, nome='Segredo', codigo='SEG-1', quantidade=5
        )
        self.client.force_login(self.user)
        response = self.client.get('/estoque/pecas/')
        self.assertContains(response, 'Pastilha')
        self.assertNotContains(response, 'Segredo')
        self.assertEqual(self.client.get(f'/estoque/pecas/{foreign.pk}/editar/').status_code, 404)

    def test_sku_unique_per_workshop(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EstoqueItem.objects.create(oficina=self.oficina, nome='Outra', codigo='PAS-1')
        EstoqueItem.objects.create(oficina=self.other, nome='Outra', codigo='PAS-1')

    def test_order_usage_is_idempotent_and_reversible(self):
        order = self.create_order()
        part = OrdemServicoPartItem.objects.create(
            oficina=self.oficina, ordem_servico=order, estoque_item=self.item,
            description=self.item.nome, quantity=2, unit_price=self.item.preco_venda,
            unit_cost=self.item.custo_unitario,
        )
        reconcile_order_part(part, user=self.user)
        reconcile_order_part(part, user=self.user)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 8)
        self.assertEqual(EstoqueMovimentacao.objects.filter(tipo='os_usage').count(), 1)
        reverse_order_part(part, user=self.user)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 10)
        self.assertEqual(EstoqueMovimentacao.objects.filter(tipo='reversal').count(), 1)

    def test_http_add_uses_snapshot_and_rejects_excess(self):
        order = self.create_order()
        self.client.force_login(self.user)
        url = f'/os/{order.pk}/part/add/'
        response = self.client.post(url, {
            'estoque_item': self.item.pk, 'quantity': 2, 'unit_price': '35.00',
        })
        self.assertEqual(response.status_code, 302)
        part = order.part_items.get()
        self.assertEqual(part.description, 'Pastilha')
        self.assertEqual(part.unit_price, Decimal('35.00'))
        self.assertEqual(part.unit_cost, Decimal('20.00'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 8)
        response = self.client.post(url, {
            'estoque_item': self.item.pk, 'quantity': 9, 'unit_price': '35.00',
        }, follow=True)
        self.assertContains(response, 'Estoque insuficiente')
        self.assertEqual(order.part_items.count(), 1)

    def test_http_rejects_part_from_another_workshop(self):
        foreign = EstoqueItem.objects.create(
            oficina=self.other, nome='Segredo', codigo='SEG-POST', quantidade=20
        )
        order = self.create_order()
        self.client.force_login(self.user)
        response = self.client.post(f'/os/{order.pk}/part/add/', {
            'estoque_item': foreign.pk, 'quantity': 1, 'unit_price': '10.00',
        }, follow=True)
        self.assertEqual(order.part_items.count(), 0)
        foreign.refresh_from_db()
        self.assertEqual(foreign.quantidade, 20)
        self.assertContains(response, 'Faça uma escolha válida')

    def test_quantity_change_only_applies_difference_and_remove_reverses(self):
        order = self.create_order()
        part = OrdemServicoPartItem.objects.create(
            oficina=self.oficina, ordem_servico=order, estoque_item=self.item,
            description='Pastilha', quantity=2, unit_price=Decimal('35'),
            unit_cost=Decimal('20'),
        )
        reconcile_order_part(part, user=self.user)
        self.client.force_login(self.user)
        update_url = f'/os/{order.pk}/part/{part.pk}/update/'
        self.client.post(update_url, {'quantity': 3, 'unit_price': '35.00'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 7)
        self.client.post(update_url, {'quantity': 1, 'unit_price': '35.00'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 9)
        self.client.post(f'/os/{order.pk}/part/{part.pk}/delete/')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 10)
        self.assertEqual(EstoqueMovimentacao.objects.filter(item=self.item).count(), 4)

    def test_cancel_is_idempotent(self):
        order = self.create_order()
        part = OrdemServicoPartItem.objects.create(
            oficina=self.oficina, ordem_servico=order, estoque_item=self.item,
            description='Pastilha', quantity=2, unit_price=Decimal('35'),
        )
        reconcile_order_part(part, user=self.user)
        self.client.force_login(self.user)
        url = f'/os/{order.pk}/update-status/'
        self.client.post(url, {'status': 'canceled', 'note': 'Cliente desistiu'})
        self.client.post(url, {'status': 'canceled', 'note': 'Repetido'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 10)
        self.assertEqual(EstoqueMovimentacao.objects.filter(tipo='reversal').count(), 1)

    def test_search_endpoint_is_tenant_scoped(self):
        EstoqueItem.objects.create(
            oficina=self.other, nome='Pastilha secreta', codigo='OUT-1', quantidade=5
        )
        order = self.create_order()
        self.client.force_login(self.user)
        response = self.client.get(f'/os/{order.pk}/part/search/?q=Pastilha')
        payload = response.json()['results']
        self.assertEqual([row['id'] for row in payload], [self.item.pk])

    def overview_totals(self):
        self.client.force_login(self.user)
        return self.client.get(reverse('agenda:stock_overview')).context['totals']

    def test_overview_financial_totals_multiple_parts_and_tenant_isolation(self):
        EstoqueItem.objects.create(
            oficina=self.oficina, nome='Óleo', codigo='OLE-1', quantidade=5,
            custo_unitario=Decimal('12.34'), preco_venda=Decimal('20.99'),
        )
        EstoqueItem.objects.create(
            oficina=self.oficina, nome='Zerada', codigo='ZER-1', quantidade=0,
            custo_unitario=Decimal('999.99'), preco_venda=Decimal('1999.99'),
        )
        EstoqueItem.objects.create(
            oficina=self.other, nome='Outra oficina', codigo='OUT-FIN', quantidade=100,
            custo_unitario=Decimal('100'), preco_venda=Decimal('500'),
        )
        totals = self.overview_totals()
        self.assertEqual(totals['cost_value'], Decimal('261.700000000000'))
        self.assertEqual(totals['sale_value'], Decimal('454.950000000000'))
        self.assertEqual(totals['potential_profit'], Decimal('193.250000000000'))

    def test_overview_empty_stock_and_zero_prices(self):
        self.item.delete()
        totals = self.overview_totals()
        self.assertEqual(totals['cost_value'], Decimal('0'))
        self.assertEqual(totals['sale_value'], Decimal('0'))
        self.assertEqual(totals['potential_profit'], Decimal('0'))
        EstoqueItem.objects.create(
            oficina=self.oficina, nome='Grátis', codigo='ZERO-PRICE', quantidade=7,
            custo_unitario=Decimal('0'), preco_venda=Decimal('0'),
        )
        totals = self.overview_totals()
        self.assertEqual(totals['potential_profit'], Decimal('0'))

    def test_overview_preserves_negative_potential_profit(self):
        self.item.custo_unitario = Decimal('100')
        self.item.preco_venda = Decimal('80')
        self.item.quantidade = 2
        self.item.save()
        totals = self.overview_totals()
        self.assertEqual(totals['cost_value'], Decimal('200'))
        self.assertEqual(totals['sale_value'], Decimal('160'))
        self.assertEqual(totals['potential_profit'], Decimal('-40'))

    def test_overview_updates_after_stock_and_price_changes(self):
        move_stock(item=self.item, movement_type='entry', quantity=2)
        totals = self.overview_totals()
        self.assertEqual(totals['cost_value'], Decimal('240'))
        self.assertEqual(totals['sale_value'], Decimal('420'))
        move_stock(item=self.item, movement_type='exit', quantity=3, note='Consumo')
        self.item.refresh_from_db()
        self.item.custo_unitario = Decimal('21.11')
        self.item.preco_venda = Decimal('40.22')
        self.item.save()
        totals = self.overview_totals()
        self.assertEqual(totals['cost_value'], Decimal('189.990000000000'))
        self.assertEqual(totals['sale_value'], Decimal('361.980000000000'))
        self.assertEqual(totals['potential_profit'], Decimal('171.990000000000'))

    def test_brazilian_currency_format_uses_decimal(self):
        self.assertEqual(brl(Decimal('12450.90')), 'R$ 12.450,90')
        self.assertEqual(brl(Decimal('-40')), '-R$ 40,00')
