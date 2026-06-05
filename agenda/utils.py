import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def enviar_whatsapp(booking, to_number=None):
    """
    Envia uma mensagem via API de WhatsApp com os dados do agendamento.

    booking: instância de Booking
    to_number: telefone destino no formato internacional (ex: '55119xxxx') opcional.

    A função tenta enviar a mensagem e registra erros sem lançar exceções.
    """
    if not getattr(settings, 'WHATSAPP_API_URL', None):
        logger.warning('WHATSAPP_API_URL não configurado - pulando envio de WhatsApp')
        return False

    to_number = to_number or getattr(settings, 'WHATSAPP_TO_NUMBER', None)
    if not to_number:
        logger.warning('Número destino do WhatsApp não definido - pulando envio')
        return False

    # Monta a mensagem conforme especificado
    start_time = booking.start_time.strftime('%H:%M') if booking.start_time else ''
    end_hour = ''
    if booking.start_time and booking.duration_minutes:
        # calcula horário final (assume mesma data)
        from datetime import datetime, timedelta
        dummy_date = datetime.combine(booking.scheduled_date, booking.start_time)
        end_dt = dummy_date + timedelta(minutes=booking.duration_minutes)
        end_hour = end_dt.strftime('%H:%M')

    # Resolve display do tipo de serviço corretamente (campo é CharField com choices)
    service_display = ''
    if hasattr(booking, 'get_service_type_display'):
        try:
            service_display = booking.get_service_type_display() or ''
        except Exception:
            service_display = str(getattr(booking, 'service_type', '') or '')
    else:
        service_display = str(getattr(booking, 'service_type', '') or '')

    message = (
        f"Novo agendamento!\n\n"
        f"Cliente: {booking.full_name}\n"
        f"Carro: {booking.vehicle_model or ''} {booking.vehicle_year or ''}\n"
        f"Serviço: {service_display}\n"
        f"Data: {booking.scheduled_date.strftime('%d/%m/%Y')}\n"
        f"Horário: {start_time}{(' - ' + end_hour) if end_hour else ''}\n\n"
        "Acesse o painel para mais detalhes."
    )

    payload = {
        'to': to_number,
        'from': getattr(settings, 'WHATSAPP_FROM_NUMBER', ''),
        'message': message,
    }

    headers = {
        'Content-Type': 'application/json',
    }
    token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
    if token:
        headers['Authorization'] = token

    try:
        resp = requests.post(settings.WHATSAPP_API_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info('WhatsApp enviado com sucesso para %s (booking=%s)', to_number, getattr(booking, 'pk', None))
        return True
    except requests.RequestException as exc:
        logger.exception('Falha ao enviar WhatsApp: %s', exc)
        return False
