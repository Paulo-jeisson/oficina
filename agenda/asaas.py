from datetime import timedelta
import logging

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Assinatura

logger = logging.getLogger(__name__)


class AsaasError(Exception):
    """Erro controlado para falhas de comunicacao com a API do Asaas."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def get_asaas_headers(api_key=None):
    """Monta os headers da API sem expor a chave no codigo-fonte."""
    token = api_key or settings.ASAAS_API_KEY
    if not token:
        raise AsaasError('Configure ASAAS_API_KEY no arquivo .env antes de chamar o Asaas.')
    return {
        'access_token': token,
        'Content-Type': 'application/json',
    }


def create_customer(payload):
    """Cria um cliente no Asaas usando o cliente padrao da integracao."""
    return AsaasClient().create_customer(payload)


class AsaasClient:
    def __init__(self):
        self.base_url = settings.ASAAS_BASE_URL.rstrip('/')
        self.api_key = settings.ASAAS_API_KEY

    def _headers(self):
        return get_asaas_headers(self.api_key)

    def _request(self, method, path, payload=None, params=None):
        # Todas as chamadas passam por este metodo para padronizar timeout,
        # headers, tratamento de erro e logs sem vazar credenciais.
        url = f'{self.base_url}{path}'
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                params=params,
                headers=self._headers(),
                timeout=20,
            )
        except requests.RequestException as exc:
            logger.exception('Falha de rede ao chamar o Asaas em %s %s.', method.upper(), path)
            raise AsaasError('Nao foi possivel conectar ao Asaas. Tente novamente em instantes.') from exc

        if response.status_code >= 400:
            detail = self._extract_error_message(response)
            logger.warning(
                'Asaas retornou erro %s em %s %s: %s',
                response.status_code,
                method.upper(),
                path,
                detail,
            )
            raise AsaasError(detail, status_code=response.status_code)

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            logger.exception('Asaas retornou uma resposta sem JSON valido em %s %s.', method.upper(), path)
            raise AsaasError('O Asaas retornou uma resposta inesperada.') from exc

    def _extract_error_message(self, response):
        try:
            data = response.json()
        except ValueError:
            return response.text[:300] or 'Erro nao identificado no Asaas.'

        errors = data.get('errors') or []
        if errors:
            descriptions = [error.get('description') for error in errors if error.get('description')]
            if descriptions:
                return ' '.join(descriptions)
        return data.get('description') or data.get('message') or 'Erro nao identificado no Asaas.'

    def test_connection(self):
        """Consulta leve para validar credenciais e URL Sandbox/Producao."""
        return self._request('get', '/customers', params={'limit': 1})

    def create_customer(self, payload):
        """Cria cliente no Asaas para uso futuro em cobrancas Pix, boleto e cartao."""
        clean_payload = {key: value for key, value in payload.items() if value}
        if not clean_payload.get('name'):
            raise AsaasError('Informe o nome do cliente antes de cria-lo no Asaas.')
        data = self._request('post', '/customers', clean_payload)
        logger.info('Cliente criado no Asaas com sucesso: %s', data.get('id', 'sem-id'))
        return data

    def create_pix_payment(self, customer_id, value, due_date=None, description='', external_reference=''):
        """Cria uma cobranca Pix sem alterar registros locais de assinatura."""
        due_date = due_date or timezone.localdate() + timedelta(days=2)
        payload = {
            'customer': customer_id,
            'billingType': 'PIX',
            'value': float(value),
            'dueDate': due_date.isoformat(),
            'description': description,
            'externalReference': external_reference,
        }
        payload = {key: value for key, value in payload.items() if value}
        data = self._request('post', '/payments', payload)
        logger.info('Cobranca Pix criada no Asaas com sucesso: %s', data.get('id', 'sem-id'))
        return data

    def get_pix_qr_code(self, payment_id):
        """Busca QR Code, copia e cola e vencimento de uma cobranca Pix."""
        if not payment_id:
            raise AsaasError('ID da cobranca Pix nao informado.')

        # Logs temporarios para depurar a resposta do Asaas no Sandbox.
        path = f'/payments/{payment_id}/pixQrCode'
        url = f'{self.base_url}{path}'
        headers = self._headers()
        headers['accept'] = 'application/json'
        logger.warning('Asaas Pix QR Code debug - endpoint: GET %s', path)
        logger.warning('Asaas Pix QR Code debug - url chamada: %s', url)
        logger.warning('Asaas Pix QR Code debug - payment_id: %s', payment_id)

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            logger.exception('Asaas Pix QR Code debug - falha de rede para payment_id %s.', payment_id)
            raise AsaasError('Nao foi possivel conectar ao Asaas para buscar o QR Code Pix.') from exc

        logger.warning('Asaas Pix QR Code debug - codigo HTTP: %s', response.status_code)

        try:
            data = response.json()
        except ValueError as exc:
            logger.error('Asaas Pix QR Code debug - resposta sem JSON: %s', response.text)
            raise AsaasError('O Asaas retornou uma resposta sem JSON valido.', status_code=response.status_code) from exc

        logger.warning('Asaas Pix QR Code debug - JSON completo retornado: %s', data)

        if response.status_code >= 400:
            detail = self._extract_error_message(response)
            raise AsaasError(detail, status_code=response.status_code)

        return data

    def create_test_pix_charge(self, assinatura, value='5.00'):
        """Cria uma cobranca Pix Sandbox para validar o fluxo de assinaturas SaaS."""
        customer_id = self.ensure_customer(assinatura)
        due_date = timezone.localdate() + timedelta(days=2)
        payment = self.create_pix_payment(
            customer_id=customer_id,
            value=value,
            due_date=due_date,
            description=f'Teste Pix Sandbox - {assinatura.oficina.nome}',
            external_reference=f'teste-pix-oficina-{assinatura.oficina_id}-{timezone.now().strftime("%Y%m%d%H%M%S")}',
        )
        qr_code = self.get_pix_qr_code(payment.get('id'))
        return {
            'payment': payment,
            'qr_code': qr_code,
            'due_date': due_date.isoformat(),
        }

    def ensure_customer(self, assinatura):
        if assinatura.asaas_customer_id:
            return assinatura.asaas_customer_id

        oficina = assinatura.oficina
        payload = {
            'name': oficina.nome,
            'email': oficina.email or oficina.dono.email,
            'mobilePhone': oficina.telefone,
            'cpfCnpj': ''.join(ch for ch in oficina.documento if ch.isdigit()),
            'externalReference': f'oficina-{oficina.pk}',
            'notificationDisabled': False,
        }
        data = self.create_customer(payload)
        assinatura.asaas_customer_id = data['id']
        assinatura.save(update_fields=['asaas_customer_id', 'updated_at'])
        return assinatura.asaas_customer_id

    def create_payment(self, assinatura, billing_type, request=None):
        customer_id = self.ensure_customer(assinatura)
        due_date = timezone.localdate() + timedelta(days=2)

        payload = {
            'customer': customer_id,
            'billingType': billing_type,
            'value': float(assinatura.monthly_amount),
            'dueDate': due_date.isoformat(),
            'description': f'Assinatura mensal Oficina Online - {assinatura.oficina.nome}',
            'externalReference': f'assinatura-{assinatura.pk}',
        }

        data = self._request('post', '/payments', payload)
        assinatura.asaas_payment_id = data.get('id', '')
        assinatura.asaas_invoice_url = data.get('invoiceUrl', '')
        assinatura.payment_method = (
            Assinatura.FormaPagamento.PIX
            if billing_type == 'PIX'
            else Assinatura.FormaPagamento.CARTAO_CREDITO
        )
        assinatura.save(update_fields=[
            'asaas_payment_id',
            'asaas_invoice_url',
            'payment_method',
            'updated_at',
        ])
        return data
