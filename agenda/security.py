import hashlib
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.http import url_has_allowed_host_and_scheme


SPREADSHEET_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')
ALLOWED_LOGO_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_LOGO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def safe_spreadsheet_value(value):
    """Keep user-controlled text from being interpreted as a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def validate_logo_upload(upload):
    if not upload:
        return

    max_bytes = getattr(settings, 'MAX_LOGO_UPLOAD_BYTES', 5 * 1024 * 1024)
    if upload.size > max_bytes:
        max_megabytes = max_bytes / (1024 * 1024)
        raise ValidationError(f'O logo deve ter no maximo {max_megabytes:g} MB.')

    extension = Path(upload.name).suffix.lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        raise ValidationError('Envie um logo JPG, PNG ou WEBP.')

    content_type = getattr(upload, 'content_type', '')
    if content_type and content_type.lower() not in ALLOWED_LOGO_CONTENT_TYPES:
        raise ValidationError('O tipo de arquivo do logo nao e permitido.')

    try:
        position = upload.tell()
        image = Image.open(upload)
        if image.width * image.height > 25_000_000:
            raise ValidationError('As dimensoes do logo sao excessivas.')
        image.verify()
        if image.format not in {'JPEG', 'PNG', 'WEBP'}:
            raise ValidationError('O conteudo do logo nao e uma imagem permitida.')
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError('O arquivo enviado nao e uma imagem valida.') from exc
    finally:
        upload.seek(position if 'position' in locals() else 0)


def get_client_ip(request):
    remote_addr = request.META.get('REMOTE_ADDR', '')
    trusted_proxies = getattr(settings, 'TRUSTED_PROXY_IPS', ())
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if remote_addr in trusted_proxies and forwarded_for:
        return forwarded_for.split(',', 1)[0].strip()
    return remote_addr or 'unknown'


def rate_limit_key(scope, identifier):
    digest = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
    return f'security-rate:{scope}:{digest}'


def rate_limit_exceeded(scope, identifier, limit, window_seconds, increment=True):
    key = rate_limit_key(scope, identifier)
    current = cache.get(key, 0)
    if current >= limit:
        return True
    if increment:
        if cache.add(key, 1, timeout=window_seconds):
            return False
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window_seconds)
    return False


def clear_rate_limit(scope, identifier):
    cache.delete(rate_limit_key(scope, identifier))


def safe_local_redirect(request, candidate, fallback):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback
