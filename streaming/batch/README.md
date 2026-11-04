# Pipeline batch — ingestão dos crimes pela API oficial de Chicago

Substitui a cópia do dataset público do BigQuery (`bigquery-public-data.chicago_crime`), usada no Trabalho 1. Agora a coleta é feita **por script, direto da fonte oficial**: a API SODA do portal de dados da prefeitura, dataset *Crimes – 2001 to Present* (`ijzp-q8t2`). Ela roda de forma **automática e incremental**.

## Arquitetura

```
Cloud Scheduler (diário, 07:00 America/Chicago, OIDC)
        │
        ▼
Cloud Run function `ingest-chicago` (Python 3.12)          streaming/batch/ingest_chicago/main.py
        │  GET data.cityofchicago.org/resource/ijzp-q8t2.json
        │  paginado: $limit=50000, $order=:id, $offset
        ▼
GCS  gs://crimes-chicago-pdm-2026/bronze/chicago_crimes/
        ingestion_date=AAAA-MM-DD/run=<id>/part-NNNN.json     (NDJSON, imutável)
        │  load job (append)
        ▼
BigQuery  crimes_chicago.tb_crimes_bronze_api               sql/01_bronze_api.sql
        (tudo STRING + _ingested_at, _run_id, _mode, _source_file; partição diária por _ingested_at)
        │  consulta programada diária 08:00: MERGE             sql/04_merge_silver.sql
        ▼
BigQuery  crimes_chicago.tb_crimes_silver                   regras em sql/02_fn_crimes_silver.sql
        │
        ▼
gold_* e modelos do Trabalho 1 (sem alteração)
```

## Decisões

| Decisão | Por quê |
|---|---|
| **Fonte oficial (API SODA)** em vez do espelho no BigQuery público | É assim que um pipeline real consome dados de terceiros (feedback do T1). |
| **Paginação** com `$limit=50000` e `$order=:id` | No T1, o download em bloco do portal era cortado em ~100 s / ~107 MB. Páginas pequenas não têm esse limite e podem ser repetidas em caso de falha (retry com backoff exponencial para 429/5xx). |
| **Incremental por `updated_on`**, não pela data do crime | O portal publica com ~7 dias de atraso e **reclassifica registros antigos** (tipo do crime, prisão etc.). Filtrar pela data do crime perderia essas correções. |
| Marca d'água com `>=` | Relê a borda de propósito: é melhor duplicar do que perder. Quem deduplica é o MERGE. |
| **Bronze append-only, tudo STRING** | A bronze guarda o dado exatamente como veio. Tipagem e regra de negócio ficam na silver, então mudanças no portal não quebram a carga. |
| Metadados `_ingested_at`, `_run_id`, `_mode`, `_source_file` | Linhagem: de qualquer linha dá para voltar à execução e ao arquivo bruto no GCS. |
| Partição da bronze por dia de ingestão | Cada execução cai numa partição. O MERGE diário lê só os últimos 2 dias. |
| **Silver por MERGE idempotente** (`unique_key`, só atualiza se `updated_on` for mais novo) | Rodar duas vezes não duplica nem faz o registro regredir. |
| Regras da silver numa *table function* (`fn_crimes_silver`) | A mesma lógica serve à reconstrução completa e ao MERGE diário, sem SQL duplicado. |
| Silver particionada por mês da ocorrência + cluster `distrito_policial, tipo_crime` | ~310 partições (limite de 10.000). As consultas da gold filtram exatamente por essas chaves. |
| Fuso: parse **sem conversão** | A API devolve a hora de parede de Chicago sem fuso. Mantém a convenção do T1 (a gold lê com `TZ='UTC'`). |

## Como executar (Cloud Shell, a partir da raiz do repo)

```bash
# 1. tabela bronze
bq query --use_legacy_sql=false < sql/01_bronze_api.sql

# 2. deploy da function (cria/atualiza)
cd streaming/batch/ingest_chicago && SODA_APP_TOKEN=<opcional> bash deploy.sh

# 3. carga histórica (um ano por chamada)
cd .. && bash backfill.sh 2001 2026

# 4. validação: contagem por ano API x bronze nova x bronze do T1
python3 validar_backfill.py

# 5. agendamentos (Scheduler 07:00 Chicago + MERGE programado), a partir da raiz do repo
cd ../.. && bash streaming/batch/agendar.sh

# 6. incremental manual (é o que o Scheduler chama todo dia)
URL=$(gcloud functions describe ingest-chicago --gen2 --region us-central1 --format='value(serviceConfig.uri)')
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?mode=incremental"
```

A resposta da function resume a execução: `run_id`, filtro usado, marca d'água, páginas, registros lidos, linhas carregadas e caminho do bruto no GCS.

## Permissões

| Conta | Papéis |
|---|---|
| `sa-ingest` (executa a function) | BigQuery Data Editor, BigQuery Job User, Storage Object Admin no bucket |
| `sa-scheduler` (chama a function) | Cloud Run Invoker no serviço `ingest-chicago` |
