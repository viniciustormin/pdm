# 3️⃣ Modelo de probabilidade de prisão

Prevê a chance de uma ocorrência terminar em prisão, evento a evento. A API usa o
`model.joblib` e o `contrato_features.json` publicados no GCS.

## Base de treino

A `gold_treino_prisao` vem da `tb_crimes_silver_v2` e das janelas de jogo do T1.

| Split | Período | Linhas | Taxa de prisão |
|---|---|---:|---:|
| Treino | 2021–2024 | 972.704 | 12,65% |
| Validação | 2025 | 237.824 | 16,16% |
| Teste | 2026, até 10/09 | 161.154 | 15,66% |

| Feature | Convenção |
|---|---|
| `tipo_crime`, `local_ocorrencia` | `UPPER(TRIM())`; local vazio vira `NAO_INFORMADO` |
| `distrito_policial` | Categoria |
| `hora` | 0–23, horário de parede de Chicago; categoria |
| `dia_semana` | 1 = domingo ... 7 = sábado; categoria |
| `mes` | 1–12; categoria |
| `eh_domestico` | Booleano |
| `teve_jogo` | Mesmo distrito e `janela_ini <= t < janela_fim`, só em janelas de jogo |

O teste termina na última janela conhecida. Depois dela, `teve_jogo` seria falso por
falta de calendário, não por falta de jogo.

## Treino e escolha do campeão

- **Baseline:** taxa de prisão por tipo de crime no treino.
- **Candidatos:** `LogisticRegression` e `HistGradientBoostingClassifier`, com o
  pré-processamento dentro do `Pipeline`.
- **Campeão:** maior PR-AUC na validação; em empate (diferença menor que 0,001), menor
  log loss.
- **Teste:** lido só depois da escolha, e avaliado apenas no campeão.
- **Registro:** dois runs no Vertex AI Experiments, com `experiment_tensorboard=False`.

## Resultados

O campeão é o `HistGradientBoostingClassifier`, que também superou o baseline em
PR-AUC e log loss nas duas avaliações.

| Avaliação | Modelo | PR-AUC | Log loss | Brier | ROC-AUC | Média prevista | Taxa real |
|---|---|---:|---:|---:|---:|---:|---:|
| Validação (2025) | Baseline | 0,540 | 0,335 | 0,097 | 0,789 | 13,2% | 16,2% |
| Validação (2025) | Regressão logística | 0,611 | 0,317 | 0,094 | 0,835 | 13,4% | 16,2% |
| Validação (2025) | **HGB** | **0,668** | **0,292** | **0,087** | **0,865** | 13,8% | 16,2% |
| Teste (2026) | Baseline | 0,529 | 0,331 | 0,096 | 0,787 | 13,1% | 15,7% |
| Teste (2026) | **HGB** | **0,642** | **0,296** | **0,087** | **0,855** | 13,6% | 15,7% |

Runs no Vertex AI Experiments: `logreg-20261104-165259` e `hgb-20261104-165259`.

## Registro

A versão 1 está no Vertex AI Model Registry como `modelo-prisao`, com o alias `campeao`,
sem deploy e sem Endpoint. Os artefatos ficam em
`gs://crimes-chicago-pdm-2026/models/prisao/v1`, e a API em produção usa esse modelo.

## Limitações conhecidas

- **`teve_jogo` sem efeito claro:** na comparação com controles pareados desde 2021, a
  taxa de prisão foi de 11,9% com jogo e 12,1% sem jogo.
- **NHL:** os jogos não têm horário de início na silver de jogos e não geram janela.
  Parte dos crimes do distrito 12 fica com `teve_jogo = FALSE` mesmo com jogo.
- **Mudança ao longo do tempo:** a taxa de prisão é maior em 2025 e 2026 do que no
  treino. No teste, a média prevista ficou em 13,6%, contra 15,7% de taxa real, então as
  probabilidades tendem a ficar abaixo do observado.

## Como rodar

Use Python 3.12 e uma conta com acesso ao BigQuery, ao bucket e ao Vertex AI.

No BigQuery, nesta ordem:

1. [`sql/modelo_01_diagnostico.sql`](../sql/modelo_01_diagnostico.sql)
2. [`sql/modelo_02_gold_treino_prisao.sql`](../sql/modelo_02_gold_treino_prisao.sql)
3. [`sql/modelo_03_validacao.sql`](../sql/modelo_03_validacao.sql)

No terminal:

```bash
cd model
pip install -r requirements-dev.txt
gcloud auth application-default login
pytest tests -q

# 10 mil linhas; publica o v0 e o contrato no GCS
python treinar.py v0

# Rode uma vez: grava o campeão e as métricas em artefatos/completo
python treinar.py completo

# Publica no GCS e no Model Registry, sem deploy e sem Endpoint
IMAGEM=$(gcloud run services describe api-prisao --region us-central1 \
  --format='value(spec.template.spec.containers[0].image)')
python registrar.py --artefatos artefatos/completo --container "$IMAGEM"
```

## Versões

O scikit-learn é 1.9.1 no treino, na API e na imagem registrada. O teste
`test_versoes_iguais_as_da_api` falha se os requisitos divergirem.

O Registry usa a imagem da própria API porque ela tem a mesma versão. O registro serve
para versionamento: a predição acontece no Cloud Run, e o `/predict` da API não usa o
formato de um Endpoint do Vertex.
