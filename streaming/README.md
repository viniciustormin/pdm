# Pipeline de streaming — replay de crimes reais via Pub/Sub + Dataflow

## Ideia
O professor aceitou streaming simulado. Usamos **replay acelerado de dados reais**:

- o **batch** (API oficial → bronze → silver) carrega o histórico completo;
- a partir de uma **data de corte (01/10/2026)**, os crimes reais são reapresentados como se estivessem chegando agora: em ordem cronológica, com o relógio acelerado (padrão: 1 dia por minuto).

Como o dado é real, dá para **conferir o streaming contra o batch** registro a registro (`sql/12_conferencia_stream.sql`).

Consultar a API "em tempo real" não serviria: o portal publica com ~7 dias de atraso e atualiza uma vez por dia.

## Arquitetura
```
producer/publisher.py ──► Pub/Sub crimes-eventos ─┬─► crimes-eventos-dataflow ─► Dataflow (Beam)
  (API SODA a partir do corte,                     │      LerPubSub → Limpar ─┬─► tb_crimes_stream
   ou replay.jsonl offline)                        │                          ├─► tb_crimes_stream_erros (dead-letter)
                                                   │                          └─► Janela1min → Contar → tb_crimes_stream_agg_1min
                                                   └─► crimes-eventos-debug (espiar mensagens na demo)

vw_crimes_unificado = silver (batch, < 01/10) ∪ stream (≥ 01/10)
```

## Decisões
- **Mesmas regras da silver** (`transforms.py`, funções puras com testes em `tests/`): distrito entre 1 e 25 (recuperado pelo beat quando falta), caixa de coordenadas de Chicago e data sem conversão de fuso.
- **Dead-letter:** evento inválido não some; vai para `tb_crimes_stream_erros` com o motivo e o payload.
- **Janela fixa de 60 s:** contagem por distrito e tipo (processamento com estado no Beam).
- **Tabela de stream particionada pela data da ocorrência e clusterizada por distrito e tipo:** as mesmas chaves da silver e das consultas.
- **Sem `arrest` no evento:** é o alvo do modelo e não se sabe no momento da ocorrência. `prob_prisao` fica reservada para o Trabalho Final, em que o Dataflow chama a API.
- **Custo:** 1 worker `n1-standard-1`. O job de streaming cobra enquanto estiver de pé: **drenar depois de usar**.

## Como executar (Cloud Shell, na raiz do repo)
```bash
bash streaming/setup_gcp.sh                       # tópico, assinaturas, tabelas, view, sa-dataflow (uma vez)
python3 -m venv ~/venv-beam && ~/venv-beam/bin/pip install -r streaming/requirements.txt -r producer/requirements.txt

# testes das regras de limpeza
cd streaming && ~/venv-beam/bin/python -m pytest -q tests

# subir no Dataflow
PATH=~/venv-beam/bin:$PATH bash run_dataflow.sh &

# gerar eventos (em outro terminal)
cd ../producer
~/venv-beam/bin/python publisher.py --corte 2026-10-01 --velocidade 1440 --sujo 0.05
#   plano B sem internet: --salvar replay.jsonl antes, --fonte arquivo --arquivo replay.jsonl na hora

# ver mensagens chegando no tópico
gcloud pubsub subscriptions pull crimes-eventos-debug --auto-ack --limit 5

# parar (não esquecer!)
gcloud dataflow jobs list --region us-central1 --status=active
gcloud dataflow jobs drain <JOB_ID> --region us-central1
```

## Resultado do teste (21/10)
7.603 eventos reais em ~12 min. Batch e stream tiveram data/hora idêntica em 100% das ocorrências em comum, e a latência mediana foi de 158 ms. Detalhes em `docs/evidencias/conferencia_streaming.txt` e no grafo do job em `docs/evidencias/dataflow_grafo_job.jpg`.
