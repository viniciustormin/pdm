# PDM — Trabalho 2: arquitetura híbrida batch + streaming

Evolução do Trabalho 1: pipeline de streaming em tempo real processando dados
contínuos lado a lado com a base histórica em lote no BigQuery, modelo
registrado no Vertex AI e serviço de inferência via API REST no Cloud Run.

**Domínio:** ocorrências policiais de Chicago cruzadas com o calendário
esportivo da cidade.

- 🔗 **API em produção:** `https://api-prisao-XXXX.us-central1.run.app` *(preencher após o deploy)*

---

## Arquitetura

```
                    ┌──────────────────────────────────────┐
                    │          FONTE OFICIAL               │
                    │   API de dados abertos de Chicago    │
                    └──────────────┬───────────────────────┘
                                   │
          ┌────────────────────────┴────────────────────────┐
          │                                                 │
   ┌──────▼───────┐                                 ┌───────▼────────┐
   │   BATCH      │                                 │   STREAMING    │
   │              │                                 │                │
   │ Cloud Run    │                                 │ producer.py    │
   │ ingest-      │                                 │      │         │
   │ chicago      │                                 │      ▼         │
   │      │       │                                 │   Pub/Sub      │
   │      ▼       │                                 │ crimes-eventos │
   │  GCS NDJSON  │                                 │      │         │
   │      │       │                                 │      ▼         │
   │      ▼       │                                 │   Dataflow     │
   │ tb_crimes_   │                                 │  (Apache Beam) │
   │ bronze_api   │                                 │      │         │
   │      │       │                                 │      ▼         │
   │      ▼       │                                 │ tb_crimes_     │
   │ tb_crimes_   │                                 │ stream         │
   │ silver       │                                 │ _erros / _agg  │
   └──────┬───────┘                                 └───────┬────────┘
          │                                                 │
          └────────────────────┬────────────────────────────┘
                               ▼
                   ┌───────────────────────┐
                   │ vw_crimes_unificado   │
                   │  (batch + streaming,  │
                   │   coluna `origem`)    │
                   └───────────┬───────────┘
                               │
                               ▼
                   ┌───────────────────────┐
                   │  gold_treino_prisao   │
                   │          │            │
                   │          ▼            │
                   │   Vertex AI Model     │
                   │   Registry (v0)       │
                   │          │            │
                   │          ▼            │
                   │   GCS model.joblib    │
                   └───────────┬───────────┘
                               │
                               ▼
                   ┌───────────────────────┐
                   │  Cloud Run            │
                   │  api-prisao           │
                   │  POST /predict        │
                   └───────────────────────┘
```

**O que o modelo prevê:** a probabilidade de uma ocorrência policial terminar
em prisão, evento a evento. Isso prepara o Trabalho Final, em que o Dataflow
chamará a API a cada evento do streaming.

---

## Ambiente

| Recurso | Valor |
|---|---|
| Projeto GCP | `pdm-crimes-chicago` |
| Dataset BigQuery | `crimes_chicago` |
| Bucket GCS | `crimes-chicago-pdm-2026` |
| Região | `us-central1` |
| Tópico Pub/Sub | `crimes-eventos` |

---

## Estrutura do repositório

```
.
├── producer/      # 1️⃣ gerador de eventos para o Pub/Sub
├── streaming/     # 2️⃣ pipeline Dataflow + ingestão batch
├── model/         # 3️⃣ treino, registro no Vertex AI
├── api/           # 4️⃣ API REST + Cloud Run
├── sql/           # scripts SQL das tabelas e views
└── docs/          # diagrama, evidências, apresentação
```

---

## 1️⃣ Pub/Sub e integração no BigQuery

> *(responsável: preencher)*

Como rodar:

```bash
# TODO
```

---

## 2️⃣ Streaming (Dataflow) e ingestão batch

> *(responsável: preencher)*

Como rodar:

```bash
# TODO
```

---

## 3️⃣ Modelo

> *(responsável: preencher)*

Como rodar:

```bash
# TODO
```

---

## 4️⃣ API REST no Cloud Run

Serviço de inferência em tempo real. Recebe uma ocorrência policial e devolve
a probabilidade de ela terminar em prisão.

### Endpoints

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/health` | 200 com o modelo carregado, 503 se o startup falhou |
| `GET` | `/model-info` | Versão, origem e contrato de features do modelo |
| `POST` | `/predict` | Uma ocorrência → `prob_prisao`, versão e latência |
| `POST` | `/predict/batch` | Até 500 ocorrências numa chamada |
| `GET` | `/docs` | Swagger UI |

### Exemplo

```bash
curl -X POST "https://api-prisao-XXXX.us-central1.run.app/predict" \
  -H 'Content-Type: application/json' \
  -d '{
    "tipo_crime": "NARCOTICS",
    "local_ocorrencia": "STREET",
    "distrito_policial": 19,
    "data_hora_local_chicago": "2026-07-04T19:00:00",
    "eh_domestico": false
  }'
```

```json
{
  "prob_prisao": 0.662177,
  "predicao": true,
  "teve_jogo": true,
  "teve_jogo_origem": "consultado",
  "versao_modelo": "v0",
  "latencia_ms": 7.918
}
```

### Rodando local

```bash
cd api
pip install -r requirements-dev.txt
python scripts/criar_modelo_v0_stub.py --saida data/modelo_stub
MODEL_URI=data/modelo_stub/model.joblib uvicorn app.main:app --port 8080
```

### Justificativa de processamento

A feature `teve_jogo` exige saber se a ocorrência caiu numa janela pós-jogo da
`gold_janelas` — informação que **o evento do Pub/Sub não carrega**.

Consultar o BigQuery a cada requisição resolveria, ao custo de centenas de
milissegundos. Como são 5.404 janelas e menos de 1 MB, a API carrega o
conjunto inteiro em memória no startup e resolve localmente, por busca binária
com prefixo de máximo do fim — estrutura necessária porque as janelas se
sobrepõem (doubleheaders da MLB geram duas janelas no mesmo estádio).

O modelo também é carregado uma única vez, no startup, a partir de `MODEL_URI`.

**Latência mediana medida:** `__ ms` *(preencher após o deploy)*

Detalhes completos em [`api/README-api.md`](api/README-api.md).

---

## Entregáveis

- [ ] Apresentação em PDF
- [ ] Código do producer Pub/Sub
- [ ] Código do pipeline de streaming
- [ ] Código da API REST com Dockerfile e scripts de deploy
- [ ] Scripts SQL das tabelas de streaming e integração no BigQuery
- [ ] Este README
- [ ] Link da API no Cloud Run
