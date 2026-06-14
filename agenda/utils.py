from .whatsapp import build_booking_owner_whatsapp_url


def enviar_whatsapp(booking, to_number=None):
    return build_booking_owner_whatsapp_url(booking)
