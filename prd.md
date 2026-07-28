Vamos iniciar a CORREÇÃO DA AUDITORIA DE PRODUÇÃO do SaaS Oficina.

Você já realizou a auditoria e encontrou problemas críticos.

Nesta etapa NÃO quero corrigir todo o relatório.

Quero implementar somente:

SPRINT 1 — FUNDAÇÃO SEGURA DE PRODUÇÃO

Objetivo:

Preparar a aplicação Django para operar corretamente em ambiente de produção com PostgreSQL, configurações seguras e deploy reproduzível, SEM alterar regras de negócio de OS, estoque, financeiro, agendamento ou Asaas nesta etapa.

IMPORTANTE:

Preserve integralmente as funcionalidades existentes.

Antes de alterar cada arquivo, analise sua utilização no projeto.

Não remova funcionalidades funcionando.

Não faça refatoração estética desnecessária.

Não altere frontend, design system ou templates, exceto se absolutamente necessário para funcionamento da configuração.

Faça mudanças pequenas, rastreáveis e testáveis.

==================================================

1. CONFIGURAÇÃO DE AMBIENTE
   ==================================================

Analise app/settings.py.

Hoje a auditoria identificou que DEBUG é lido do ambiente mas posteriormente sobrescrito por:

DEBUG = True

Corrija isso.

DEBUG deve ser controlado exclusivamente por variável de ambiente.

Desenvolvimento:

DEBUG=True

Produção:

DEBUG=False

Nunca usar DEBUG=True hardcoded.

Garanta parsing seguro de boolean.

Exemplo conceitual:

DEBUG = os.getenv("DEBUG", "False").lower() == "true"

ou solução equivalente compatível com a estrutura atual.

==================================================
2. SECRET_KEY
=============

SECRET_KEY deve obrigatoriamente vir de variável de ambiente.

Nunca:

SECRET_KEY = "..."

Não gerar uma chave automaticamente silenciosamente em produção.

Se SECRET_KEY estiver ausente no ambiente de produção, a aplicação deve falhar claramente na inicialização.

Não altere o histórico Git nesta etapa.

Informe ao final que a chave de produção precisa ser rotacionada antes do lançamento.

Não exponha a nova chave em logs ou código.

==================================================
3. POSTGRESQL
=============

A auditoria identificou SQLite como banco ativo.

Configure suporte adequado a PostgreSQL via variáveis de ambiente.

Preserve SQLite para desenvolvimento local se a arquitetura atual precisar dele.

Produção deve utilizar PostgreSQL.

Variáveis sugeridas:

DB_ENGINE
DB_NAME
DB_USER
DB_PASSWORD
DB_HOST
DB_PORT

ou DATABASE_URL caso o projeto já utilize esse padrão.

Não coloque credenciais reais no código.

Exemplo esperado conceitualmente:

produção
→ PostgreSQL

desenvolvimento local
→ SQLite opcional

Confirme que migrations existentes continuam compatíveis.

==================================================
4. DEPENDÊNCIA POSTGRESQL
=========================

Adicione o driver PostgreSQL adequado ao projeto.

Considere:

psycopg[binary]

ou alternativa compatível com a versão de Python e Django utilizada pelo projeto.

Não escolha uma dependência incompatível com Python 3.14/Django atual.

Fixe versões de maneira reproduzível.

==================================================
5. MANIFESTO DE DEPENDÊNCIAS
============================

A auditoria identificou ausência de:

requirements.txt

pyproject.toml

ou lockfile apropriado.

Analise como o projeto está estruturado e escolha o método menos invasivo.

Garanta que as dependências necessárias estejam declaradas, incluindo as realmente utilizadas pelo projeto, por exemplo:

Django
requests
Pillow
openpyxl
reportlab
PostgreSQL driver
Gunicorn

Não adicione pacotes desnecessários.

Não faça pip freeze cego incluindo ferramentas aleatórias do ambiente.

Declare apenas dependências pertencentes ao projeto.

==================================================
6. SETTINGS DE SEGURANÇA
========================

Quando DEBUG=False, configurar corretamente:

SECURE_SSL_REDIRECT

SESSION_COOKIE_SECURE

CSRF_COOKIE_SECURE

SESSION_COOKIE_HTTPONLY

SECURE_CONTENT_TYPE_NOSNIFF

X_FRAME_OPTIONS

SECURE_REFERRER_POLICY

SECURE_PROXY_SSL_HEADER

Considere que produção terá:

Cliente
↓ HTTPS
Nginx
↓
Gunicorn
↓
Django

SECURE_PROXY_SSL_HEADER deve refletir corretamente o proxy reverso.

Não habilite configurações incompatíveis com desenvolvimento local.

==================================================
7. HSTS
=======

NÃO coloque HSTS agressivo cegamente.

Prepare configuração por ambiente.

Somente habilitar HSTS em produção quando HTTPS estiver funcionando corretamente.

Criar suporte para:

SECURE_HSTS_SECONDS

SECURE_HSTS_INCLUDE_SUBDOMAINS

SECURE_HSTS_PRELOAD

Mas começar conservadoramente.

Não utilizar preload antes de confirmar toda a infraestrutura HTTPS.

==================================================
8. ALLOWED_HOSTS
================

ALLOWED_HOSTS deve vir do ambiente.

Aceitar lista separada por vírgulas.

Exemplo:

ALLOWED_HOSTS=seudominio.com,[www.seudominio.com](http://www.seudominio.com)

Não usar:

ALLOWED_HOSTS = ["*"]

em produção.

==================================================
9. CSRF_TRUSTED_ORIGINS
=======================

Configurar via ambiente.

Exemplo:

CSRF_TRUSTED_ORIGINS=https://seudominio.com,https://www.seudominio.com

Não hardcode domínio fictício.

==================================================
10. PROXY NGINX
===============

Prepare Django corretamente para receber HTTPS através do Nginx.

Verificar:

SECURE_PROXY_SSL_HEADER

X-Forwarded-Proto

Host

Não habilitar USE_X_FORWARDED_HOST sem necessidade comprovada.

==================================================
11. GUNICORN
============

Adicionar Gunicorn ao projeto.

Criar uma configuração inicial segura.

Não inventar quantidade fixa de workers como verdade absoluta.

Permitir configuração via ambiente:

WEB_CONCURRENCY
GUNICORN_TIMEOUT

Definir defaults conservadores para ambiente pequeno.

A configuração deverá ser ajustada posteriormente de acordo com:

CPU
RAM
teste de carga

==================================================
12. NGINX
=========

Se a infraestrutura estiver versionada no projeto, criar ou corrigir configuração de exemplo para produção.

Caso não esteja, criar documentação/config de deployment sem inserir domínio real obrigatório.

Nginx deve:

receber HTTPS;
servir static;
servir/proteger media adequadamente;
proxy_pass para Gunicorn;
enviar Host;
enviar X-Real-IP;
enviar X-Forwarded-For;
enviar X-Forwarded-Proto.

Não expor Gunicorn diretamente à internet.

==================================================
13. ARQUIVO .ENV.EXAMPLE
========================

Criar:

.env.example

SEM valores secretos.

Exemplo:

DEBUG=False
SECRET_KEY=
ALLOWED_HOSTS=
CSRF_TRUSTED_ORIGINS=

DB_ENGINE=postgresql
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=5432

ASAAS_API_KEY=
ASAAS_WEBHOOK_TOKEN=

etc.

Mapear todas as variáveis realmente utilizadas no projeto.

Nunca copiar valores reais do .env.

==================================================
14. .GITIGNORE
==============

Confirmar proteção para:

.env
.env.*
!.env.example

arquivos de banco local;
logs;
cache;
venv;
arquivos temporários;
credenciais.

Não remover arquivos necessários já versionados sem analisar impacto.

==================================================
15. LOGGING MÍNIMO DE PRODUÇÃO
==============================

Criar configuração básica de logging apropriada para Django.

Registrar:

erros;
warnings;
eventos operacionais relevantes.

Não registrar:

SECRET_KEY;
senha;
token Asaas;
API keys;
dados de cartão;
payload Pix completo;
credenciais.

Não corrigir ainda os logs específicos do módulo Asaas; isso pertence à Sprint de pagamentos.

==================================================
16. PÁGINAS DE ERRO
===================

Garantir que com DEBUG=False erros internos não mostrem traceback ao cliente.

Se já houver tratamento apropriado, preservar.

Não é necessário fazer redesign.

==================================================
17. CHECKS
==========

Após as alterações execute:

python manage.py check

python manage.py check --deploy

Execute também os testes atuais:

python manage.py test agenda

Nenhum teste que atualmente passa pode ser quebrado silenciosamente.

Se algum warning de deploy permanecer propositalmente por depender de HTTPS/domínio real, documente claramente.

==================================================
18. POSTGRESQL LOCAL/TESTE
==========================

Prepare a aplicação para teste com PostgreSQL.

NÃO apague o SQLite atual.

NÃO migre dados automaticamente sem confirmação.

Mostre quais comandos seriam necessários para:

criar banco;
configurar .env;
executar migrate;
executar testes.

Não execute operação destrutiva.

==================================================
19. NÃO CORRIGIR NESTA SPRINT
=============================

Ainda NÃO mexer em:

lógica do webhook Asaas;
idempotência Asaas;
agendamento concorrente;
modelo Booking;
ExclusionConstraint;
lógica de conclusão da OS;
cancelamento financeiro;
reabertura de OS;
estoque;
order_number;
exports;
formula injection;
rate limiting;
brute force;
uploads;
managers multiempresa.

Esses itens serão tratados nas próximas Sprints.

Quero isolar as mudanças.

==================================================
20. TESTE DE REGRESSÃO
======================

Compare comportamento antes/depois.

Confirmar que continuam funcionando:

login;
cadastro;
dashboard;
agenda;
OS;
estoque;
financeiro;
assinatura.

Nesta etapa não é necessário alterar esses módulos.

==================================================
RELATÓRIO FINAL
===============

Ao terminar, apresente:

SPRINT 1 — FUNDAÇÃO DE PRODUÇÃO

ARQUIVOS ALTERADOS

arquivo
→ alteração realizada
→ motivo

CONFIGURAÇÃO

DEBUG
SECRET_KEY
PostgreSQL
HTTPS
cookies
CSRF
proxy
Gunicorn
Nginx
dependências

TESTES

python manage.py check:
resultado

python manage.py check --deploy:
resultado

python manage.py test agenda:
quantidade de testes aprovados/falhados

WARNINGS RESTANTES

liste e explique.

VARIÁVEIS DE AMBIENTE

liste todas as variáveis necessárias sem mostrar valores secretos.

POSTGRESQL

mostrar como ativar PostgreSQL localmente para o próximo teste.

PENDÊNCIAS

listar problemas da auditoria que NÃO foram corrigidos porque pertencem às próximas etapas.

DECISÃO

Dizer se a Sprint 1 foi concluída com sucesso.

Não afirmar que o SaaS está pronto para produção.

Ainda teremos:

Sprint 2 — integridade OS/estoque/financeiro
Sprint 3 — agendamento e concorrência
Sprint 4 — segurança Asaas
Sprint 5 — segurança complementar/multiempresa
Sprint 6 — PostgreSQL, concorrência e carga

Faça as alterações agora.
