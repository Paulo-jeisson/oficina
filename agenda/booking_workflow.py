from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Booking, Oficina


@transaction.atomic
def create_booking(booking):
    """Serializa reservas por oficina e confirma a disponibilidade no commit."""
    oficina = Oficina.objects.select_for_update().get(pk=booking.oficina_id)
    assigned_box = Booking.find_first_available_box(
        booking.scheduled_date,
        booking.start_time,
        booking.duration_minutes,
        oficina=oficina,
    )
    if assigned_box is None:
        raise ValidationError('O horario selecionado ja esta ocupado. Escolha outro horario.')
    booking.assigned_box = assigned_box
    booking.save()
    return booking
