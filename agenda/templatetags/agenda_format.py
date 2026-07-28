from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def brl(value):
    """Formata Decimal como moeda brasileira sem converter para float."""
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal('0')
    sign = '-' if amount < 0 else ''
    formatted = f'{abs(amount):,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return f'{sign}R$ {formatted}'
