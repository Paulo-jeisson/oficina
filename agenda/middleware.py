from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from .models import Oficina


SUBSCRIPTION_ALLOWED_PATH_NAMES = (
    'home',
    'plans',
    'contact',
    'signup',
    'login',
    'logout',
    'password_reset',
    'password_reset_done',
    'password_reset_confirm',
    'password_reset_complete',
    'subscription_blocked',
    'subscription_pay',
    'asaas_webhook',
    'public_booking',
    'public_booking_success',
    'available_slots',
)

SUBSCRIPTION_ALLOWED_PATH_PREFIXES = (
    '/static/',
    '/media/',
    '/webhooks/asaas/',
    '/oficina/',
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
        path = request.path_info
        url_name = ''
        try:
            url_name = resolve(path).url_name
        except Resolver404:
            url_name = ''

        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return False
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return False
        if any(path.startswith(prefix) for prefix in SUBSCRIPTION_ALLOWED_PATH_PREFIXES):
            return False
        if url_name in SUBSCRIPTION_ALLOWED_PATH_NAMES:
            return False

        return True
