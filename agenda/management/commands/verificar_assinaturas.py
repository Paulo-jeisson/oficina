from django.core.management.base import BaseCommand
from django.utils import timezone

from agenda.models import Assinatura, Oficina


class Command(BaseCommand):
    help = 'Verifica assinaturas vencidas e bloqueia clientes apos 2 dias sem pagamento.'

    def handle(self, *args, **options):
        hoje = timezone.localdate()
        criadas = 0
        atualizadas = 0
        bloqueadas = 0

        for oficina in Oficina.objects.all():
            _, created = Assinatura.objects.get_or_create(oficina=oficina)
            if created:
                criadas += 1

        for assinatura in Assinatura.objects.select_related('oficina').all():
            status_anterior = assinatura.status
            assinatura.refresh_status(reference_date=hoje)
            if assinatura.status != status_anterior:
                atualizadas += 1
            if assinatura.status == Assinatura.Status.BLOQUEADO and status_anterior != Assinatura.Status.BLOQUEADO:
                bloqueadas += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Assinaturas verificadas. Criadas: {criadas}. Atualizadas: {atualizadas}. Bloqueadas: {bloqueadas}.'
            )
        )
