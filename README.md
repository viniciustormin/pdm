# PDM — Trabalho 2: arquitetura híbrida batch + streaming

Evolução do Trabalho 1: pipeline de streaming em tempo real processando dados
contínuos lado a lado com a base histórica em lote no BigQuery, modelo
registrado no Vertex AI e serviço de inferência via API REST no Cloud Run.

**Domínio:** ocorrências policiais de Chicago cruzadas com o calendário
esportivo da cidade.

- 🔗 **API em produção:** `https://api-prisao-1007851295296.us-central1.run.app`

---

## Arquitetura

Diagrama completo: [`docs/evidencias/arquitetura.svg`](docs/evidencias/arquitetura.svg).

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
   │ Cloud Run    │                                 │ publisher.py   │
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
                   └───────────────────────┘

   tb_crimes_silver_v2 + gold_janelas (T1)
                   │
                   ▼
           gold_treino_prisao
                   │
                   ▼  model/treinar.py
          GCS model.joblib + contrato_features.json
             │                          │
             │ MODEL_URI                │ model/registrar.py
             ▼                          ▼
   Cloud Run api-prisao         Vertex AI Model Registry
   POST /predict                modelo-prisao (sem Endpoint)
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

## Particionamento e processamento

| Tabela | Partição e cluster | Por quê |
|---|---|---|
| `tb_crimes_bronze_api` | Dia de ingestão | Cada execução cai em uma partição, e o MERGE diário lê só os últimos 2 dias |
| `tb_crimes_silver_v2` | Mês de `data_ocorrencia`; cluster por distrito e tipo | Cerca de 310 partições, dentro do limite de 10.000, com as chaves usadas nas consultas |
| `tb_crimes_stream` | `data_ocorrencia`; cluster por distrito e tipo | Mesmas chaves da silver e das consultas |
| `tb_crimes_stream_erros` | Dia de recebimento | Separa os eventos rejeitados por dia |
| `tb_crimes_stream_agg_1min` | Dia da janela; cluster por distrito | Consulta das contagens de 1 minuto |
| `gold_treino_prisao` | Ano | Cada split lê só os seus anos, e a separação temporal fica visível |

| Processamento | Papel |
|---|---|
| **Batch** | Carrega o histórico pela API oficial e captura reclassificações por `updated_on` |
| **Streaming** | Reapresenta crimes reais a partir de 01/10/2026, valida cada evento e grava no BigQuery com baixa latência |
| **Inferência** | Carrega modelo e janelas de jogo uma vez no startup, para responder sem consultar o BigQuery |

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

O gerador `producer/publisher.py` reapresenta crimes reais da API oficial a partir
de uma data de corte, em ordem cronológica e com o relógio acelerado. Os eventos
vão em JSON para o tópico `crimes-eventos`, sem o campo `arrest`, que é o alvo do
modelo.

A view `vw_crimes_unificado` lê o batch até 30/09/2026 e o streaming a partir de
01/10/2026, com a coluna `origem`.

- Gerador e demonstração: [`streaming/README.md`](streaming/README.md)
- View: [`sql/11_vw_unificada.sql`](sql/11_vw_unificada.sql)
- Consultas da demonstração: [`sql/30_demo_ao_vivo.sql`](sql/30_demo_ao_vivo.sql)

Como rodar, depois de preparar o ambiente descrito em `streaming/README.md`:

```bash
cd producer
python publisher.py --corte 2026-10-01 --velocidade 1440 --sujo 0.05
```

---

## 2️⃣ Streaming (Dataflow) e ingestão batch

**Streaming:** o pipeline Apache Beam lê a assinatura `crimes-eventos-dataflow`,
aplica as regras da silver e grava em `tb_crimes_stream`. Eventos inválidos vão
para `tb_crimes_stream_erros` com o motivo, e `tb_crimes_stream_agg_1min` guarda a
contagem por janelas de 60 segundos.

**Batch:** a função `ingest-chicago` lê a API oficial de forma paginada e
incremental, grava NDJSON no GCS e carrega `tb_crimes_bronze_api`. Um MERGE
idempotente atualiza a silver.

- Streaming: [`streaming/README.md`](streaming/README.md)
- Batch: [`streaming/batch/README.md`](streaming/batch/README.md)
- Evidências: [conferência do streaming](docs/evidencias/conferencia_streaming.txt),
  [grafo do Dataflow](docs/evidencias/dataflow_grafo_job.jpg) e
  [validação do backfill](docs/evidencias/validacao_backfill.txt)

Resultados registrados em 21/10/2026: 7.603 eventos no replay, latência mediana de
158 ms entre publicação e gravação, e 8.662.966 registros no backfill, sem diferença
em relação à API oficial em nenhum ano.

Como rodar:

```bash
# Streaming: infraestrutura, uma vez
bash streaming/setup_gcp.sh

# Streaming: subir o job; drene depois de usar, porque ele cobra enquanto estiver de pé
cd streaming && bash run_dataflow.sh

# Batch: disparo incremental manual
URL=$(gcloud functions describe ingest-chicago --gen2 --region us-central1 --format='value(serviceConfig.uri)')
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?mode=incremental"
```

---

## 3️⃣ Modelo

Prevê a probabilidade de uma ocorrência terminar em prisão. O treino usa 2021–2024,
a validação usa 2025 e o teste usa 2026 até a última janela de jogo conhecida. Os
candidatos são regressão logística e HistGradientBoosting, comparados com a taxa de
prisão por tipo de crime.

O campeão foi o HistGradientBoosting. No teste, obteve PR-AUC de 0,642 e log loss de
0,296, contra 0,529 e 0,331 do baseline.

O campeão está no Vertex AI Model Registry como `modelo-prisao`, com o alias
`campeao`, e a API em produção usa a versão v1.

Detalhes em [`model/README.md`](model/README.md).

Como rodar, com Python 3.12:

```bash
cd model
pip install -r requirements-dev.txt
pytest tests -q
python treinar.py v0
python treinar.py completo

IMAGEM=$(gcloud run services describe api-prisao --region us-central1 \
  --format='value(spec.template.spec.containers[0].image)')
python registrar.py --artefatos artefatos/completo --container "$IMAGEM"
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
curl -X POST "https://api-prisao-1007851295296.us-central1.run.app/predict" \
  -H 'Content-Type: application/json' \
  -d '{
    "tipo_crime": "NARCOTICS",
    "local_ocorrencia": "STREET",
    "distrito_policial": 19,
    "data_hora_local_chicago": "2026-07-04T19:00:00",
    "eh_domestico": false
  }'
```

Resposta real da API com o modelo v1:

```json
{
  "prob_prisao": 0.957003,
  "predicao": true,
  "limiar": 0.5,
  "teve_jogo": false,
  "teve_jogo_origem": "consultado",
  "id_janela": null,
  "unique_key": null,
  "versao_modelo": "v1",
  "latencia_ms": 13.379
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

**Latência medida no Cloud Run:** mediana de 303,68 ms no total, incluindo rede e TLS,
e de 15,66 ms só na inferência, em 20 requisições com o cold start excluído
([evidência](docs/evidencias/latencia_cloudrun.txt)).

Detalhes completos em [`api/README-api.md`](api/README-api.md).

---

## Entregáveis

- [ ] Apresentação em PDF
- [x] Código do producer Pub/Sub
- [x] Código do pipeline de streaming
- [x] Código da API REST com Dockerfile e scripts de deploy
- [x] Scripts SQL das tabelas de streaming e integração no BigQuery
- [x] Este README
- [x] Link da API no Cloud Run
