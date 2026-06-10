import re
from urllib.parse import quote

from django.conf import settings


def support(request):
    support_number = re.sub(r'\D+', '', getattr(settings, 'SUPORTE_WHATSAPP', '') or '')
    support_message = 'Olá, preciso de ajuda com o sistema Gestão Oficina Oficial.'

    if not support_number:
        return {'support_whatsapp_url': ''}

    return {
        'support_whatsapp_url': f'https://wa.me/{support_number}?text={quote(support_message)}',
    }
