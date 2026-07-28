import os


wsgi_app = 'app.wsgi:application'
bind = os.getenv('GUNICORN_BIND', '127.0.0.1:8000')
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
timeout = int(os.getenv('GUNICORN_TIMEOUT', '30'))
graceful_timeout = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))
accesslog = '-'
errorlog = '-'
capture_output = True
