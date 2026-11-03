# 4️⃣ API REST + Cloud Run

Serviço de inferência em tempo real. Recebe uma ocorrência policial de Chicago
e devolve a probabilidade de ela terminar em prisão.

**URL:** `https://api-prisao-XXXX.us-central1.run.app` *(preencher após o deploy)*

---

## Arquitetura

```
Pub/Sub ──► Dataflow ──► BigQuery
                │
                └──(Trabalho Final)──► POST /predict ──► prob_prisao
                                            │
                                   ┌────────┴────────┐
                                   │   Cloud Run     │
                                   │   api-prisao    │
                                   │                 │
                                   │  modelo .joblib │◄── GCS (MODEL_URI)
                                   │  índice janelas │◄── CSV embarcado
                                   └─────────────────┘
```

Dois artefatos são carregados **uma vez, no startup**, e reaproveitados entre
requisições:

1. **O modelo** (`model.joblib`), baixado do GCS a partir de `MODEL_URI` e
   guardado em cache em `/tmp/modelo`. Carregar por requisição multiplicaria a
   latência por dez ou mais.
2. **O índice de janelas de jogo**, lido de um CSV embarcado na imagem.

### Por que o índice de janelas existe

A `gold_treino_prisao` usa `teve_jogo` como feature, cruzando a ocorrência com
a `gold_janelas` do Trabalho 1. Mas o evento que o producer publica no Pub/Sub
**não carrega essa informação** — ele tem tipo, local, distrito e horário.

Ir ao BigQuery a cada requisição resolveria, ao custo de centenas de
milissegundos — justamente o que está sendo avaliado. Então a API carrega as
5.404 janelas de jogo (menos de 1 MB) em memória e resolve localmente.

A estrutura é, por distrito, uma lista ordenada por início mais um prefixo de
máximo do fim. Isso responde "existe janela cobrindo este instante?" por busca
binária **mesmo com janelas sobrepostas** — e elas se sobrepõem: doubleheaders
da MLB geram duas janelas no mesmo estádio, e a validação do T1 encontrou 1.839
crimes em duas janelas e 62 em três.

O campo `teve_jogo` também pode vir **no request**, e nesse caso tem
precedência sobre a consulta. É o caminho que o Dataflow usa no Trabalho Final,
quando ele já resolveu a janela antes de chamar a API. A resposta diz qual
caminho foi usado, em `teve_jogo_origem`.

---

## Endpoints

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/health` | 200 com o modelo carregado, 503 se o startup falhou |
| `GET` | `/model-info` | Versão, origem, contrato de features, cobertura do índice |
| `POST` | `/predict` | Uma ocorrência → `prob_prisao`, versão e latência |
| `POST` | `/predict/batch` | Até 500 ocorrências numa chamada |
| `GET` | `/docs` | Swagger UI gerado pelo FastAPI |

### Exemplo

```bash
curl -X POST "$URL/predict" \
  -H 'Content-Type: application/json' \
  -d '{
    "tipo_crime": "NARCOTICS",
    "local_ocorrencia": "STREET",
    "distrito_policial": 19,
    "data_hora_local_chicago": "2026-07-04T19:00:00",
    "eh_domestico": false,
    "unique_key": "demo-001"
  }'
```

```json
{
  "prob_prisao": 0.662177,
  "predicao": true,
  "limiar": 0.5,
  "teve_jogo": true,
  "teve_jogo_origem": "consultado",
  "id_janela": "-1002",
  "unique_key": "demo-001",
  "versao_modelo": "v0",
  "latencia_ms": 7.918
}
```

`latencia_ms` é só o tempo de inferência. O tempo total visto pelo cliente
inclui rede e TLS, e o `teste_latencia.sh` mede os dois lado a lado.

### Entrada inválida

O Pydantic valida antes de o modelo ser chamado e devolve **422** com o campo
e o motivo:

```bash
curl -X POST "$URL/predict" -H 'Content-Type: application/json' \
  -d '{"tipo_crime":"THEFT","local_ocorrencia":"STREET",
       "distrito_policial":99,"data_hora_local_chicago":"ontem",
       "eh_domestico":false}'
# 422 — distrito fora da faixa 1-31 e data não parseável
```

Campos **extras** no evento são ignorados de propósito: o producer pode evoluir
o formato sem derrubar a API.

---

## Convenções de feature — a parte que mais quebra

Se a API calcular uma feature de um jeito e o treino de outro, a predição sai
errada **sem lançar exceção nenhuma**. As três convenções abaixo estão
implementadas em `app/features.py` e cobertas por teste.

| Feature | Convenção | Por quê |
|---|---|---|
| `dia_semana` | `isoweekday() % 7 + 1` → 1 = domingo, 7 = sábado | Igual ao `EXTRACT(DAYOFWEEK)` do BigQuery, que montou a gold |
| `hora` | 0–23, horário de parede de Chicago | Sem offset, assume Chicago; com offset, converte |
| `mes` | 1–12 | — |

A ordem das colunas entregues ao modelo vem do `contrato_features.json`
publicado junto do `.joblib`, não de uma lista fixa no código. Quando o treino
mudar as features, só o contrato muda.

---

## Rodando local

```bash
pip install -r requirements-dev.txt

# modelo de desenvolvimento (sintético, NÃO é o do trabalho)
python scripts/criar_modelo_v0_stub.py --saida data/modelo_stub
cp data/janelas_jogo.csv.exemplo data/janelas_jogo.csv

MODEL_URI=data/modelo_stub/model.joblib \
JANELAS_CSV=data/janelas_jogo.csv \
uvicorn app.main:app --reload --port 8080
```

Swagger em `http://localhost:8080/docs`.

### Testes

```bash
pytest tests/ -q      # 28 testes
```

Cobrem o contrato HTTP, os 422, a convenção de dia da semana, a conversão de
fuso, as bordas da janela (fechada no início, aberta no fim), janelas
sobrepostas, janelas que viram o dia, o override de `teve_jogo`, categoria
desconhecida no one-hot, e a concordância entre `/predict` e `/predict/batch`.

---

## Deploy

```bash
# 1. exportar as janelas reais do BigQuery (sobrescreve o exemplo)
./scripts/exportar_janelas.sh

# 2. publicar
./deploy.sh
```

O `deploy.sh` roda os testes antes de publicar e **recusa o deploy** se o CSV
de janelas tiver menos de 1.000 linhas — isso impede subir o arquivo de
exemplo de 6 linhas por engano, o que faria a API responder `teve_jogo: false`
para quase tudo, em silêncio.

### Custo

`min-instances` fica em **0** no deploy padrão. Antes da apresentação:

```bash
./deploy.sh --aquecer   # min-instances=1, sem cold start — PASSA A COBRAR
./deploy.sh --esfriar   # depois da apresentação, volta para 0
```

### Variáveis de ambiente

| Variável | Padrão | Função |
|---|---|---|
| `MODEL_URI` | `gs://crimes-chicago-pdm-2026/models/prisao/v0/model.joblib` | Modelo a carregar |
| `JANELAS_CSV` | `data/janelas_jogo.csv` | Índice de janelas |
| `JANELAS_OPCIONAL` | `false` na imagem | Se `true`, API sobe sem o CSV |
| `CACHE_DIR` | `/tmp/modelo` | Cache do download do GCS |
| `LIMIAR` | `0.5` | Corte do campo booleano `predicao` |
| `BATCH_MAX` | `500` | Teto do `/predict/batch` |

A service account do Cloud Run precisa de `roles/storage.objectViewer` no
bucket.

---

## Decisões do Dockerfile

- **`python:3.12-slim`** — a `-alpine` obrigaria a compilar numpy e scipy do
  zero, porque musl não tem wheel pronta.
- **`requirements.txt` copiado antes do código** — o Docker invalida o cache a
  partir do primeiro arquivo alterado; com essa ordem, mexer no `app/` não
  reinstala o scikit-learn.
- **Usuário não-root** (`apiuser`, uid 10001).
- **Versões fixadas** — o `.joblib` é um pickle: carregá-lo numa versão de
  scikit-learn diferente da que treinou pode falhar ou, pior, prever errado em
  silêncio. A versão tem que bater com a do `model/treinar.py` e com a do
  container do Model Registry.
- **Um worker** — o Cloud Run escala por instância; mais workers no mesmo
  container só multiplicariam a memória ocupada pelo modelo.
- **`tests/`, `scripts/` e `data/modelo_stub/` fora da imagem** via
  `.dockerignore`.

Se o modelo falhar ao carregar no startup, o container **não entra em crash
loop**: ele sobe e o `/health` passa a devolver 503 com o motivo. Diagnosticar
isso no Cloud Run é muito mais fácil do que ler log de container morrendo em
loop.

---

## Latência medida

```bash
./teste_latencia.sh "$URL"
```

Medição local com o modelo stub, 20 requisições, cold start excluído:

| | Total (ms) | Inferência (ms) |
|---|---|---|
| mínimo | 9,79 | 6,95 |
| **mediana** | **11,24** | **7,92** |
| máximo | 17,73 | 13,79 |

Substituir por uma medição contra o Cloud Run antes da apresentação e salvar o
print em `docs/evidencias/`.

---

## Pendências de integração

- [ ] `MODEL_URI` apontando para o v0 real (hoje aponta para o stub sintético)
- [ ] Confirmar com o responsável pelo modelo que a versão do scikit-learn no
      `requirements.txt` é a mesma do treino
- [ ] Confirmar os nomes de coluna do `contrato_features.json`: a API monta
      `tipo_crime`, `local_ocorrencia`, `distrito_policial`, `hora`,
      `dia_semana`, `mes`, `eh_domestico`, `teve_jogo`
- [ ] Rodar `scripts/exportar_janelas.sh` com a gold_janelas atual
- [ ] Medir a latência contra o Cloud Run e atualizar a tabela acima
