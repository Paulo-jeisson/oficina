from .models import Oficina


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

        return self.get_response(request)
