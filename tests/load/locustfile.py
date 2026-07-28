import os
import re

from locust import FastHttpUser, between, task
from locust.exception import StopUser


CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


class OficinaUser(FastHttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        username = os.environ.get('LOAD_TEST_USERNAME')
        password = os.environ.get('LOAD_TEST_PASSWORD')
        if not username or not password:
            raise RuntimeError('Configure LOAD_TEST_USERNAME e LOAD_TEST_PASSWORD para uma conta exclusiva de staging.')
        with self.client.get('/login/', name='GET /login/', catch_response=True) as response:
            body = response.text or ''
            match = CSRF_RE.search(body)
            if response.status_code != 200 or not match:
                response.failure('Pagina de login/CSRF indisponivel.')
                raise StopUser()
        with self.client.post(
            '/login/',
            data={
                'username': username,
                'password': password,
                'csrfmiddlewaretoken': match.group(1),
            },
            headers={'Referer': f'{self.host}/login/'},
            name='POST /login/',
            catch_response=True,
            allow_redirects=False,
        ) as login_response:
            location = login_response.headers.get('Location', '')
            if login_response.status_code != 302 or '/login/' in location:
                login_response.failure('Falha no login da conta de carga.')

    @task(5)
    def dashboard(self):
        self.client.get('/dashboard/', name='GET /dashboard/')

    @task(3)
    def orders(self):
        self.client.get('/os/', name='GET /os/')

    @task(2)
    def stock(self):
        self.client.get('/estoque/', name='GET /estoque/')

    @task(2)
    def finance(self):
        self.client.get('/financeiro/', name='GET /financeiro/')

    @task(1)
    def subscription(self):
        self.client.get('/assinatura/', name='GET /assinatura/')
