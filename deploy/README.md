# Deploy de produção

Este diretório contém exemplos, não credenciais nem domínios reais.

## PostgreSQL local

Crie usuário e banco com uma conta administrativa do PostgreSQL:

```sql
CREATE USER oficina_app WITH PASSWORD 'substitua-localmente';
CREATE DATABASE oficina_db OWNER oficina_app;
```

Configure uma cópia local de `.env.example` em `.env`:

```dotenv
DEBUG=False
SECRET_KEY=<gere-e-guarde-fora-do-git>
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost
DB_ENGINE=postgresql
DB_NAME=oficina_db
DB_USER=oficina_app
DB_PASSWORD=<senha-local>
DB_HOST=127.0.0.1
DB_PORT=5432
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

Instale dependências e aplique as migrations sem importar nem apagar o SQLite:

```bash
python -m pip install -r requirements.txt
python manage.py check
python manage.py migrate
python manage.py test agenda
```

Para testar explicitamente no PostgreSQL, mantenha `DB_ENGINE=postgresql`. O
arquivo `db.sqlite3` não é migrado nem removido por esses comandos.

## Gunicorn

Execute no Linux, dentro do virtualenv:

```bash
gunicorn -c gunicorn.conf.py
```

`WEB_CONCURRENCY` e os timeouts devem ser recalibrados com CPU, RAM e teste de
carga. Gunicorn deve escutar somente em loopback ou socket Unix, atrás do Nginx.

## Nginx e HTTPS

Copie e adapte `nginx/oficina.conf.example`, substituindo domínio e caminhos.
O Nginx deve enviar `X-Forwarded-Proto`; o Django confia nesse header por meio de
`SECURE_PROXY_SSL_HEADER`. Não exponha a porta do Gunicorn à internet.

Comece com `SECURE_HSTS_SECONDS=0`. Aumente gradualmente somente após validar
HTTPS, redirects, subdomínios e renovação dos certificados. Não habilite preload
antes dessa validação.

Antes do primeiro lançamento, gere uma nova `SECRET_KEY` e invalide a chave que
apareceu no histórico Git.

## Asaas e webhook

Crie no Asaas um webhook HTTPS apontando para `/webhooks/asaas/` e habilite
somente `PAYMENT_CONFIRMED` e `PAYMENT_RECEIVED`. Gere um token exclusivo com
no mínimo 32 caracteres, configure o mesmo valor em `ASAAS_WEBHOOK_TOKEN` e
nunca reutilize `ASAAS_API_KEY` como token do webhook.

Em produção, mantenha `ASAAS_ALLOW_TEST_CHARGES=False`. A opção só deve ser
ativada temporariamente no Sandbox. O endpoint de teste aceita apenas `POST`
autenticado de usuário staff.

Depois do deploy:

```bash
python manage.py migrate
python manage.py check --deploy
python manage.py test agenda
```

Monitore no admin os registros `AsaasWebhookEvent` com status `failed` e a fila
de webhooks no painel do Asaas. Eventos falhos retornam erro transitório para
serem reenviados; eventos duplicados são reconhecidos pelo ID único do Asaas.

## PostgreSQL real e concorrência

O ambiente isolado de homologação está em `postgres/compose.yml`. Copie
`.env.postgres.example` para um arquivo não versionado, defina senha exclusiva e
suba o serviço:

```bash
docker compose --env-file deploy/postgres/.env.postgres \
  -f deploy/postgres/compose.yml up -d
```

Configure o Django com `DB_ENGINE=postgresql`, `DB_SSLMODE=prefer` apenas para o
container local e execute:

```bash
python manage.py migrate
python manage.py check --database default
python manage.py test agenda
```

Em produção use TLS validado pelo provedor (`DB_SSLMODE=require` no mínimo),
limite de conexões compatível com `WEB_CONCURRENCY`, timeout de conexão e
`DB_STATEMENT_TIMEOUT_MS`. Os endpoints `/health/live/` e `/health/ready/`
devem ser usados respectivamente para liveness e readiness.

## Backup e restore

`scripts/backup_postgres.sh` cria dump custom, valida o índice do arquivo e
remove backups acima da retenção configurada. Agende diariamente fora do
servidor da aplicação, com criptografia, controle de acesso e alerta de falha.

Política inicial:

- backup diário e retenção mínima de 14 dias;
- cópia em outra região/conta;
- objetivo de recuperação (RPO) de até 24 horas;
- objetivo de retorno (RTO) definido após medir um restore completo;
- teste mensal de restore em banco vazio;
- nunca considerar um arquivo de backup válido sem restaurá-lo periodicamente.

O restore exige banco vazio de homologação e a trava explícita
`ALLOW_RESTORE=YES`. Nunca aponte `RESTORE_DATABASE_URL` para produção.

## Go-live

Bloqueadores obrigatórios antes de liberar clientes:

- [ ] migrations e suíte completa aprovadas no PostgreSQL da mesma versão de produção;
- [ ] teste concorrente de agendamento, estoque e número da OS aprovado;
- [ ] carga gradual de 10, 25, 50 e 100 usuários sem erros funcionais;
- [ ] backup automático monitorado e restore cronometrado;
- [ ] HTTPS, cookies, CSRF, HSTS e domínio real revisados;
- [ ] rotação de `SECRET_KEY`, credenciais PostgreSQL e chaves Asaas;
- [ ] webhook Asaas validado no ambiente real;
- [ ] observabilidade de 5xx, latência, CPU, memória, conexões e locks;
- [ ] plano de rollback da aplicação e responsável de plantão definidos;
- [ ] janela de lançamento e comunicação de incidente definidas.

O go-live é decisão **NO-GO** enquanto qualquer item obrigatório estiver sem
evidência.
