import re
from urllib.parse import quote


def normalize_phone(phone):
    digits = re.sub(r'\D+', '', phone or '')
    if not digits:
        return ''

    if len(digits) in (10, 11):
        digits = f'55{digits}'

    if not digits.startswith('55'):
        return ''

    if len(digits) not in (12, 13):
        return ''

    return digits


def build_booking_owner_message(booking):
    return (
        'Olá, foi realizado um novo agendamento.\n\n'
        f'Cliente: {booking.full_name}\n'
        f'Telefone: {booking.phone}\n'
        f'Serviço: {booking.get_service_type_display()}\n'
        f'Data: {booking.scheduled_date.strftime("%d/%m/%Y")}\n'
        f'Horário: {booking.start_time.strftime("%H:%M")}\n'
        f'Duração: {booking.duration_label}\n'
        f'Box: {booking.assigned_box_label}\n\n'
        'Por favor confirme o atendimento.'
    )


def build_booking_owner_whatsapp_url(booking):
    phone = normalize_phone(getattr(booking.oficina, 'whatsapp', '') or getattr(booking.oficina, 'telefone', ''))
    if not phone:
        return ''

    message = build_booking_owner_message(booking)
    return f'https://wa.me/{phone}?text={quote(message)}'
