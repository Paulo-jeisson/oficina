import logging
import re

import requests
from django.conf import settings
from django.utils import timezone

from .models import WhatsAppMessage

logger = logging.getLogger(__name__)


def normalize_phone(phone):
    digits = re.sub(r'\D+', '', phone or '')
    if not digits:
        return ''

    if digits.startswith('55'):
        return digits

    if len(digits) in (10, 11):
        return f'55{digits}'

    return digits


def build_booking_message(booking):
    oficina = booking.oficina
    service_display = booking.get_service_type_display() if hasattr(booking, 'get_service_type_display') else booking.service_type

    return (
        'Novo agendamento recebido!\n\n'
        f'Oficina: {oficina.nome}\n'
        f'Cliente: {booking.full_name}\n'
        f'Telefone do cliente: {booking.phone}\n'
        f'Veiculo: {booking.vehicle_brand} {booking.vehicle_model} {booking.vehicle_year}\n'
        f'Servico: {service_display}\n'
        f'Data: {booking.scheduled_date.strftime("%d/%m/%Y")}\n'
        f'Horario: {booking.time_range_label}\n\n'
        'Acesse o painel para ver os detalhes.'
    )


def get_booking_destination_phone(booking):
    oficina_phone = normalize_phone(getattr(booking.oficina, 'telefone', ''))
    if oficina_phone:
        return oficina_phone
    return normalize_phone(getattr(settings, 'WHATSAPP_TO_NUMBER', ''))


def create_whatsapp_message(booking):
    destination_phone = get_booking_destination_phone(booking)
    message_text = build_booking_message(booking)

    return WhatsAppMessage.objects.create(
        oficina=booking.oficina,
        booking=booking,
        destination_phone=destination_phone,
        message=message_text,
    )


def send_message_record(message_record):
    if not message_record.destination_phone:
        error = 'Telefone destino do WhatsApp nao definido.'
        message_record.status = WhatsAppMessage.Status.FAILED
        message_record.error = error
        message_record.save(update_fields=['status', 'error', 'updated_at'])
        logger.warning('%s booking=%s', error, message_record.booking_id)
        return False

    api_url = getattr(settings, 'WHATSAPP_API_URL', '')
    if not api_url:
        error = 'WHATSAPP_API_URL nao configurado.'
        message_record.status = WhatsAppMessage.Status.FAILED
        message_record.error = error
        message_record.save(update_fields=['status', 'error', 'updated_at'])
        logger.warning('%s booking=%s', error, message_record.booking_id)
        return False

    payload = {
        'phone': message_record.destination_phone,
        'message': message_record.message,
    }
    headers = {
        'Content-Type': 'application/json',
    }

    api_token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
    if api_token:
        headers['Authorization'] = api_token

    client_token = getattr(settings, 'WHATSAPP_CLIENT_TOKEN', '')
    if client_token:
        headers['Client-Token'] = client_token

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        error = str(exc)
        response = getattr(exc, 'response', None)
        if response is not None:
            error = f'{error} | response={response.text[:500]}'

        message_record.status = WhatsAppMessage.Status.FAILED
        message_record.error = error
        message_record.save(update_fields=['status', 'error', 'updated_at'])
        logger.exception(
            'Falha ao enviar WhatsApp para %s booking=%s',
            message_record.destination_phone,
            message_record.booking_id,
        )
        return False

    message_record.status = WhatsAppMessage.Status.SENT
    message_record.error = ''
    message_record.sent_at = timezone.now()
    message_record.save(update_fields=['status', 'error', 'sent_at', 'updated_at'])
    logger.info(
        'WhatsApp enviado para %s booking=%s',
        message_record.destination_phone,
        message_record.booking_id,
    )
    return True


def send_booking_whatsapp(booking):
    try:
        message_record = create_whatsapp_message(booking)
        return send_message_record(message_record)
    except Exception:
        logger.exception('Erro inesperado ao processar WhatsApp booking=%s', getattr(booking, 'pk', None))
        return False
