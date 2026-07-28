# Teste de carga

Execute somente contra staging com banco e conta exclusivos:

```bash
python -m pip install -r requirements-load.txt
export LOAD_TEST_USERNAME=loadtest
export LOAD_TEST_PASSWORD='<segredo fora do Git>'
locust -f tests/load/locustfile.py --headless --host=https://staging.example.com \
  --users 10 --spawn-rate 2 --run-time 5m --csv=load-10
```

Repita com 25, 50 e 100 usuários, aumentando gradualmente e observando CPU,
memória, conexões PostgreSQL, locks, erros 5xx, p95 e p99. Critérios iniciais:
zero erros funcionais, p95 abaixo de 2 s nas leituras e uso sustentado de CPU
abaixo de 80%. Ajuste os limites após medir a infraestrutura real.

O cenário é predominantemente de leitura e não deve ser apontado para produção.
Testes destrutivos de estoque, OS e pagamentos exigem massa descartável e um
plano separado.
