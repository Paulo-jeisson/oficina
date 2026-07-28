from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import EstoqueItem, EstoqueMovimentacao, OrdemServicoPartItem


@transaction.atomic
def move_stock(*, item, movement_type, quantity=None, target_quantity=None, user=None,
               note='', order=None, order_item=None, unit_cost=None):
    locked = EstoqueItem.objects.select_for_update().get(pk=item.pk, oficina=item.oficina)
    before = locked.quantidade
    if movement_type == EstoqueMovimentacao.Tipo.AJUSTE:
        if target_quantity is None or target_quantity < 0:
            raise ValidationError('Informe uma quantidade final não negativa.')
        after = int(target_quantity)
        movement_quantity = abs(after - before)
    else:
        if quantity is None or int(quantity) <= 0:
            raise ValidationError('A quantidade deve ser maior que zero.')
        movement_quantity = int(quantity)
        if movement_type in (EstoqueMovimentacao.Tipo.ENTRADA, EstoqueMovimentacao.Tipo.ESTORNO):
            after = before + movement_quantity
        else:
            after = before - movement_quantity
            if after < 0:
                raise ValidationError(
                    f'Estoque insuficiente. Disponível: {before} unidades.'
                )
    if unit_cost is not None:
        unit_cost = Decimal(unit_cost)
        if unit_cost < 0:
            raise ValidationError('O custo unitário não pode ser negativo.')
        locked.custo_unitario = unit_cost
    locked.quantidade = after
    locked.save(update_fields=['quantidade', 'custo_unitario', 'updated_at'])
    movement = EstoqueMovimentacao.objects.create(
        oficina=locked.oficina, item=locked, tipo=movement_type,
        quantidade=movement_quantity, quantidade_anterior=before,
        quantidade_posterior=after, custo_unitario=unit_cost,
        usuario=user, observacao=note, ordem_servico=order, ordem_item=order_item,
    )
    item.quantidade = after
    item.custo_unitario = locked.custo_unitario
    return movement


@transaction.atomic
def reconcile_order_part(item, *, user=None):
    # Regra do sistema: a peça é consumida ao ser adicionada à OS. O saldo
    # aplicado torna a operação idempotente e permite reconciliar só a diferença.
    order_item = OrdemServicoPartItem.objects.select_for_update().select_related(
        'estoque_item', 'ordem_servico'
    ).get(pk=item.pk)
    if not order_item.estoque_item_id:
        return order_item
    delta = order_item.quantity - order_item.stock_quantity_applied
    if delta > 0:
        move_stock(
            item=order_item.estoque_item, movement_type=EstoqueMovimentacao.Tipo.USO_OS,
            quantity=delta, user=user, note=f'Uso em {order_item.ordem_servico.order_number}',
            order=order_item.ordem_servico, order_item=order_item,
        )
    elif delta < 0:
        move_stock(
            item=order_item.estoque_item, movement_type=EstoqueMovimentacao.Tipo.ESTORNO,
            quantity=-delta, user=user, note=f'Estorno de {order_item.ordem_servico.order_number}',
            order=order_item.ordem_servico, order_item=order_item,
        )
    if delta:
        order_item.stock_quantity_applied = order_item.quantity
        order_item.save(update_fields=['stock_quantity_applied'])
    return order_item


@transaction.atomic
def reverse_order_part(item, *, user=None):
    locked = OrdemServicoPartItem.objects.select_for_update().select_related(
        'estoque_item', 'ordem_servico'
    ).get(pk=item.pk)
    if locked.estoque_item_id and locked.stock_quantity_applied:
        move_stock(
            item=locked.estoque_item, movement_type=EstoqueMovimentacao.Tipo.ESTORNO,
            quantity=locked.stock_quantity_applied, user=user,
            note=f'Peça removida de {locked.ordem_servico.order_number}',
            order=locked.ordem_servico, order_item=locked,
        )
        locked.stock_quantity_applied = 0
        locked.save(update_fields=['stock_quantity_applied'])
    return locked
