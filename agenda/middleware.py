from django.shortcuts import redirect
from django.urls import reverse

from .models import Oficina


INTERNAL_PATH_PREFIXES = (
    '/dashboard/',
    '/financeiro/',
    '/os/',
)


class OficinaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.oficina = None

        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            if hasattr(user, 'oficina') and user.oficina:
                request.oficina = user.oficina
            else:
                # create tenant automatically
                oficina = Oficina.objects.create(
                    dono=user,
                    nome=f'Oficina de {user.get_username()}',
                )
                user.oficina = oficina
                request.oficina = oficina

            if self._should_check_subscription(request):
                assinatura = request.oficina.ensure_assinatura()
                assinatura.refresh_status()
                if assinatura.is_blocked:
                    return redirect('agenda:subscription_blocked')

        return self.get_response(request)

    def _should_check_subscription(self, request):
        if request.path == reverse('agenda:subscription_blocked'):
            return False
        return any(request.path.startswith(prefix) for prefix in INTERNAL_PATH_PREFIXES)
