from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CashFlowRecord, FinanceAudit, FinancialTransaction, OrdemServico
from .stock import reconcile_order_part, reverse_order_part


EDITABLE_STATUSES = {
    OrdemServico.Status.RECEBIDO,
    OrdemServico.Status.ANALYSIS,
    OrdemServico.Status.WAITING_APPROVAL,
    OrdemServico.Status.IN_PROGRESS,
}
FINAL_STATUSES = {OrdemServico.Status.COMPLETED, OrdemServico.Status.DELIVERED}


def _locked_order(*, order_id, oficina):
    return OrdemServico.objects.select_for_update().get(pk=order_id, oficina=oficina)


def _recalculate_totals(order):
    order.service_value = sum(
        (item.total_price for item in order.service_items.all()), Decimal('0')
    )
    order.parts_value = sum(
        (item.total_price for item in order.part_items.all()), Decimal('0')
    )
    order.total_value = order.service_value + order.parts_value


def _activate_financial(order, user):
    completed_at = order.completed_at or timezone.now()
    financial, _ = FinancialTransaction.objects.update_or_create(
        ordem_servico=order,
        transaction_type='receivable',
        defaults={
            'oficina': order.oficina,
            'status': 'paid',
            'amount': order.total_value,
            'due_date': completed_at.date(),
            'paid_at': completed_at,
            'payment_method': order.payment_method,
            'description': f'Faturamento da OS {order.order_number}',
        },
    )
    active_inflow = CashFlowRecord.objects.select_for_update().filter(
        ordem_servico=order,
        entry_type='inflow',
        status='active',
    ).first()
    if active_inflow:
        active_inflow.amount = order.total_value
        active_inflow.entry_date = completed_at.date()
        active_inflow.description = f'Receita registrada para OS {order.order_number}'
        active_inflow.save(update_fields=['amount', 'entry_date', 'description'])
    else:
        CashFlowRecord.objects.create(
            oficina=order.oficina,
            ordem_servico=order,
            entry_type='inflow',
            status='active',
            amount=order.total_value,
            entry_date=completed_at.date(),
            description=f'Receita registrada para OS {order.order_number}',
        )
    FinanceAudit.objects.create(
        oficina=order.oficina,
        ordem_servico=order,
        action='OS concluída e faturamento confirmado',
        user=user,
        note=f'Valor total R$ {order.total_value:.2f}; lançamento {financial.pk}.',
    )


def _reverse_financial(order, user, reason):
    FinancialTransaction.objects.filter(
        ordem_servico=order,
        transaction_type='receivable',
    ).update(status='canceled')
    active_inflows = CashFlowRecord.objects.select_for_update().filter(
        ordem_servico=order,
        entry_type='inflow',
        status='active',
    )
    for inflow in active_inflows:
        inflow.status = 'reversed'
        inflow.save(update_fields=['status'])
        CashFlowRecord.objects.get_or_create(
            reversal_of=inflow,
            defaults={
                'oficina': order.oficina,
                'ordem_servico': order,
                'entry_type': 'outflow',
                'status': 'active',
                'amount': inflow.amount,
                'entry_date': timezone.localdate(),
                'description': f'Estorno financeiro da OS {order.order_number}: {reason}',
            },
        )
    FinanceAudit.objects.create(
        oficina=order.oficina,
        ordem_servico=order,
        action='Efeito financeiro da OS estornado',
        user=user,
        note=reason,
    )


@transaction.atomic
def complete_order(*, order_id, oficina, user=None, note=''):
    order = _locked_order(order_id=order_id, oficina=oficina)
    if order.status == OrdemServico.Status.COMPLETED:
        for part in order.part_items.select_related('estoque_item'):
            reconcile_order_part(part, user=user)
        _recalculate_totals(order)
        order.save(workflow=True)
        _activate_financial(order, user)
        return order, False
    if order.status not in EDITABLE_STATUSES:
        raise ValidationError('Esta OS não pode ser concluída a partir do estado atual.')
    for part in order.part_items.select_related('estoque_item'):
        reconcile_order_part(part, user=user)
    _recalculate_totals(order)
    order.status = OrdemServico.Status.COMPLETED
    order.completed_at = timezone.now()
    order.save(user=user, note=note or 'OS concluída', workflow=True)
    _activate_financial(order, user)
    return order, True


@transaction.atomic
def cancel_order(*, order_id, oficina, user=None, note=''):
    order = _locked_order(order_id=order_id, oficina=oficina)
    if order.status == OrdemServico.Status.CANCELED:
        return order, False
    for part in order.part_items.select_related('estoque_item'):
        reverse_order_part(part, user=user)
    _reverse_financial(order, user, note or 'Cancelamento da OS')
    order.status = OrdemServico.Status.CANCELED
    order.save(user=user, note=note or 'OS cancelada', workflow=True)
    return order, True


@transaction.atomic
def reopen_order(*, order_id, oficina, user=None, note=''):
    order = _locked_order(order_id=order_id, oficina=oficina)
    if order.status == OrdemServico.Status.IN_PROGRESS:
        return order, False
    if order.status not in FINAL_STATUSES | {OrdemServico.Status.CANCELED}:
        raise ValidationError('Somente uma OS concluída, entregue ou cancelada pode ser reaberta.')
    _reverse_financial(order, user, note or 'Reabertura da OS')
    if order.status == OrdemServico.Status.CANCELED:
        for part in order.part_items.select_related('estoque_item'):
            reconcile_order_part(part, user=user)
    # Em OS concluída o estoque permanece aplicado. Alterações após a reabertura
    # reconciliam somente a diferença via stock_quantity_applied.
    order.status = OrdemServico.Status.IN_PROGRESS
    order.completed_at = None
    order.save(user=user, note=note or 'OS reaberta', workflow=True)
    return order, True
