from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from unittest.mock import patch

from datetime import date, time

from .models import (
    AsaasPayment, AsaasWebhookEvent, Assinatura, Booking, CashFlowRecord, EstoqueItem, EstoqueMovimentacao,
    FinancialTransaction, Oficina, OrdemServico, OrdemServicoPartItem,
    OrdemServicoServiceItem,
)
from .stock import move_stock, reconcile_order_part, reverse_order_part
from .templatetags.agenda_format import brl
from .order_workflow import cancel_order, complete_order, reopen_order
from .asaas import AsaasError


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

    def create_order_items(self, order, *, apply_stock=True):
        service = OrdemServicoServiceItem.objects.create(
            oficina=self.oficina, ordem_servico=order,
            description='Mão de obra', quantity=1, unit_price=Decimal('30'),
        )
        part = OrdemServicoPartItem.objects.create(
            oficina=self.oficina, ordem_servico=order, estoque_item=self.item,
            description='Pastilha', quantity=2, unit_price=Decimal('35'),
            unit_cost=Decimal('20'),
        )
        if apply_stock:
            reconcile_order_part(part, user=self.user)
        return service, part

    def test_complete_order_is_atomic_idempotent_and_financial_matches_total(self):
        order = self.create_order()
        self.create_order_items(order)
        completed, changed = complete_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        self.assertTrue(changed)
        self.assertEqual(completed.total_value, Decimal('100'))
        financial = FinancialTransaction.objects.get(ordem_servico=order)
        self.assertEqual(financial.amount, completed.total_value)
        self.assertEqual(financial.status, 'paid')
        self.assertEqual(CashFlowRecord.objects.filter(
            ordem_servico=order, entry_type='inflow'
        ).count(), 1)
        _, changed_again = complete_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        self.assertFalse(changed_again)
        self.assertEqual(FinancialTransaction.objects.filter(ordem_servico=order).count(), 1)
        self.assertEqual(EstoqueMovimentacao.objects.filter(tipo='os_usage').count(), 1)

    def test_cancel_completed_order_reverses_stock_and_finance_once(self):
        order = self.create_order()
        self.create_order_items(order)
        complete_order(order_id=order.pk, oficina=self.oficina, user=self.user)
        _, changed = cancel_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        self.assertTrue(changed)
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(order.status, OrdemServico.Status.CANCELED)
        self.assertEqual(self.item.quantidade, 10)
        self.assertEqual(
            FinancialTransaction.objects.get(ordem_servico=order).status, 'canceled'
        )
        self.assertEqual(CashFlowRecord.objects.filter(
            ordem_servico=order, entry_type='outflow'
        ).count(), 1)
        _, changed_again = cancel_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        self.assertFalse(changed_again)
        self.assertEqual(EstoqueMovimentacao.objects.filter(tipo='reversal').count(), 1)
        self.assertEqual(CashFlowRecord.objects.filter(
            ordem_servico=order, entry_type='outflow'
        ).count(), 1)

    def test_reopen_edit_and_recomplete_updates_single_financial(self):
        order = self.create_order()
        self.create_order_items(order)
        complete_order(order_id=order.pk, oficina=self.oficina, user=self.user)
        reopened, changed = reopen_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        self.assertTrue(changed)
        self.assertEqual(reopened.status, OrdemServico.Status.IN_PROGRESS)
        self.assertIsNone(reopened.completed_at)
        self.assertEqual(
            FinancialTransaction.objects.get(ordem_servico=order).status, 'canceled'
        )
        OrdemServicoServiceItem.objects.create(
            oficina=self.oficina, ordem_servico=order,
            description='Serviço adicional', quantity=1, unit_price=Decimal('100'),
        )
        completed, _ = complete_order(
            order_id=order.pk, oficina=self.oficina, user=self.user
        )
        financial = FinancialTransaction.objects.get(ordem_servico=order)
        self.assertEqual(completed.total_value, Decimal('200'))
        self.assertEqual(financial.amount, Decimal('200'))
        self.assertEqual(financial.status, 'paid')
        self.assertEqual(FinancialTransaction.objects.filter(ordem_servico=order).count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 8)

    def test_completed_and_canceled_orders_reject_item_mutations(self):
        order = self.create_order()
        service, part = self.create_order_items(order)
        complete_order(order_id=order.pk, oficina=self.oficina, user=self.user)
        self.client.force_login(self.user)
        self.client.post(f'/os/{order.pk}/service/add/', {
            'description': 'Indevido', 'quantity': 1, 'unit_price': '50',
        })
        self.client.post(f'/os/{order.pk}/service/{service.pk}/delete/')
        self.client.post(f'/os/{order.pk}/part/{part.pk}/update/', {
            'quantity': 3, 'unit_price': '35',
        })
        self.assertEqual(order.service_items.count(), 1)
        part.refresh_from_db()
        self.assertEqual(part.quantity, 2)
        cancel_order(order_id=order.pk, oficina=self.oficina, user=self.user)
        self.client.post(f'/os/{order.pk}/service/add/', {
            'description': 'Indevido', 'quantity': 1, 'unit_price': '50',
        })
        self.client.post(f'/os/{order.pk}/part/add/', {
            'estoque_item': self.item.pk, 'quantity': 1, 'unit_price': '35',
        })
        self.assertEqual(order.service_items.count(), 1)
        self.assertEqual(order.part_items.count(), 1)

    def test_complete_rolls_back_stock_when_finance_fails(self):
        order = self.create_order()
        self.create_order_items(order, apply_stock=False)
        with patch('agenda.order_workflow._activate_financial', side_effect=RuntimeError('falha')):
            with self.assertRaises(RuntimeError):
                complete_order(
                    order_id=order.pk, oficina=self.oficina, user=self.user
                )
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(order.status, OrdemServico.Status.RECEBIDO)
        self.assertEqual(self.item.quantidade, 10)
        self.assertFalse(FinancialTransaction.objects.filter(ordem_servico=order).exists())
        self.assertFalse(EstoqueMovimentacao.objects.filter(ordem_servico=order).exists())

    def test_workflow_rejects_order_from_another_workshop(self):
        order = self.create_order()
        with self.assertRaises(OrdemServico.DoesNotExist):
            complete_order(order_id=order.pk, oficina=self.other, user=self.other_user)

    def test_complete_rolls_back_when_stock_is_insufficient(self):
        order = self.create_order()
        OrdemServicoPartItem.objects.create(
            oficina=self.oficina, ordem_servico=order, estoque_item=self.item,
            description='Pastilha', quantity=11, unit_price=Decimal('35'),
            unit_cost=Decimal('20'),
        )
        with self.assertRaises(ValidationError):
            complete_order(order_id=order.pk, oficina=self.oficina, user=self.user)
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(order.status, OrdemServico.Status.RECEBIDO)
        self.assertEqual(self.item.quantidade, 10)
        self.assertFalse(FinancialTransaction.objects.filter(ordem_servico=order).exists())


@override_settings(
    ASAAS_WEBHOOK_TOKEN='webhook-token-seguro-com-mais-de-32-caracteres',
    ASAAS_WEBHOOK_MAX_BODY_BYTES=65536,
)
class AsaasWebhookSecurityTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('asaas-owner', password='test')
        self.oficina = Oficina.objects.create(nome='Oficina Asaas', dono=self.user)
        self.assinatura = self.oficina.ensure_assinatura()
        self.assinatura.asaas_customer_id = 'cus_123'
        self.assinatura.asaas_payment_id = 'pay_123'
        self.assinatura.save(update_fields=['asaas_customer_id', 'asaas_payment_id', 'updated_at'])
        self.payment = AsaasPayment.objects.create(
            oficina=self.oficina,
            assinatura=self.assinatura,
            payment_id='pay_123',
            customer_id='cus_123',
            external_reference=f'assinatura-{self.assinatura.pk}',
            billing_type='PIX',
            amount=Decimal('99.90'),
        )
        self.url = reverse('agenda:asaas_webhook')
        self.headers = {'HTTP_ASAAS_ACCESS_TOKEN': 'webhook-token-seguro-com-mais-de-32-caracteres'}

    def payload(self, event_id='evt_123', payment_id='pay_123'):
        return {
            'id': event_id,
            'event': 'PAYMENT_RECEIVED',
            'payment': {'id': payment_id, 'status': 'RECEIVED'},
        }

    def verified_payment(self, **changes):
        data = {
            'id': 'pay_123',
            'customer': 'cus_123',
            'externalReference': f'assinatura-{self.assinatura.pk}',
            'status': 'RECEIVED',
            'billingType': 'PIX',
            'value': 99.90,
            'paymentDate': '2026-07-28',
        }
        data.update(changes)
        return data

    def post_event(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
            **self.headers,
        )

    @patch('agenda.views.AsaasClient.get_payment')
    def test_verified_payment_activates_subscription_once(self, get_payment):
        get_payment.return_value = self.verified_payment()
        response = self.post_event(self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['processed'])
        self.assinatura.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.assinatura.status, Assinatura.Status.ATIVO)
        self.assertEqual(self.assinatura.due_date, date(2026, 8, 27))
        self.assertEqual(self.payment.status, AsaasPayment.Status.RECEIVED)

        duplicate = self.post_event(self.payload())
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json()['processed'])
        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.due_date, date(2026, 8, 27))
        self.assertEqual(AsaasWebhookEvent.objects.count(), 1)
        self.assertEqual(get_payment.call_count, 1)

    @patch('agenda.views.AsaasClient.get_payment')
    def test_new_event_for_same_payment_does_not_extend_subscription(self, get_payment):
        get_payment.return_value = self.verified_payment()
        self.post_event(self.payload(event_id='evt_first'))
        response = self.post_event(self.payload(event_id='evt_second'))
        self.assertFalse(response.json()['processed'])
        self.assinatura.refresh_from_db()
        self.assertEqual(self.assinatura.due_date, date(2026, 8, 27))

    @patch('agenda.views.AsaasClient.get_payment')
    def test_forged_reference_cannot_activate_subscription(self, get_payment):
        response = self.post_event(self.payload(payment_id='pay_forged'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['processed'])
        get_payment.assert_not_called()
        self.assinatura.refresh_from_db()
        self.assertNotEqual(self.assinatura.status, Assinatura.Status.ATIVO)

    @patch('agenda.views.AsaasClient.get_payment')
    def test_remote_amount_must_match_local_charge(self, get_payment):
        get_payment.return_value = self.verified_payment(value=1.00)
        response = self.post_event(self.payload())
        self.assertFalse(response.json()['processed'])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, AsaasPayment.Status.PENDING)
        self.assertEqual(
            AsaasWebhookEvent.objects.get(event_id='evt_123').status,
            AsaasWebhookEvent.Status.IGNORED,
        )

    @patch('agenda.views.AsaasClient.get_payment')
    def test_invalid_token_is_rejected_before_api_or_database(self, get_payment):
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload()),
            content_type='application/json',
            HTTP_ASAAS_ACCESS_TOKEN='token-invalido',
        )
        self.assertEqual(response.status_code, 403)
        get_payment.assert_not_called()
        self.assertFalse(AsaasWebhookEvent.objects.exists())

    @patch('agenda.views.AsaasClient.get_payment', side_effect=AsaasError('offline'))
    def test_api_verification_failure_is_retryable_without_activation(self, get_payment):
        response = self.post_event(self.payload())
        self.assertEqual(response.status_code, 503)
        event = AsaasWebhookEvent.objects.get(event_id='evt_123')
        self.assertEqual(event.status, AsaasWebhookEvent.Status.FAILED)
        self.assinatura.refresh_from_db()
        self.assertNotEqual(self.assinatura.status, Assinatura.Status.ATIVO)
