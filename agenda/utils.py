from .whatsapp import send_booking_whatsapp


def enviar_whatsapp(booking, to_number=None):
    return send_booking_whatsapp(booking)
