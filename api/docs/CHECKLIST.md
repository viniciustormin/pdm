# Checklist — Entrega 4️⃣ API REST + Cloud Run

Marque conforme for fechando. Cada item tem o critério de "pronto".

---

## ✅ Já está feito (não precisa mexer)

- [x] FastAPI com `/health`, `/model-info`, `/predict`, `/predict/batch`
- [x] Modelo carregado uma vez no startup, caminho em `MODEL_URI`
- [x] Pydantic validando entrada, 422 em payload inválido
- [x] `hora`, `dia_semana` e `mes` na convenção do treino (1 = domingo)
- [x] Dockerfile: `python:3.12-slim`, requirements antes do código, usuário
      não-root, versões fixadas, `.dockerignore`
- [x] 28 testes de pytest passando
- [x] `deploy.sh` com `--aquecer` / `--esfriar`
- [x] `teste_latencia.sh` com 20 requisições e mediana
- [x] Coleção do Postman com 5 casos (o enunciado pede 3)
- [x] `README-api.md` com arquitetura e justificativas

---

## 🔴 BLOCO 1 — Hoje, sozinho

### 1.1 Exportar as janelas do BigQuery

Console → nova consulta → *Salvar resultados → CSV* → salvar em
`api/data/janelas_jogo.csv` (substitui o arquivo de exemplo de 6 linhas).

```sql
SELECT
  CAST(id_janela AS STRING)                          AS id_janela,
  distrito_policial,
  FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', janela_ini)   AS janela_ini,
  FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', janela_fim)   AS janela_fim,
  teve_jogo,
  IFNULL(liga, '')      AS liga,
  IFNULL(time_casa, '') AS time_casa
FROM `pdm-crimes-chicago.crimes_chicago.gold_janelas`
WHERE teve_jogo
ORDER BY distrito_policial, janela_ini;
```

O `FORMAT_DATETIME` não é cosmético: sem ele o console pode exportar em ISO
com `T` e o parser da API teria que adivinhar formato.

**Pronto quando:** `wc -l api/data/janelas_jogo.csv` devolver **5405**
(5.404 janelas + cabeçalho).

- [ ] feito

### 1.2 Verificar a cobertura das janelas para a demo

```sql
SELECT
  MAX(janela_fim)                                              AS ultima_janela,
  DATE_DIFF(CURRENT_DATE('America/Chicago'),
            DATE(MAX(janela_fim)), DAY)                        AS dias_atras,
  COUNTIF(DATE(janela_ini) >= CURRENT_DATE('America/Chicago')) AS janelas_futuras
FROM `pdm-crimes-chicago.crimes_chicago.gold_janelas`
WHERE teve_jogo;
```

Se `janelas_futuras = 0`, nenhum evento do producer cai dentro de uma janela,
porque ele usa o horário atual e a base termina em 01/09/2026. A API vai
responder `teve_jogo: false` para todos — sem erro, só sempre false.

Escolha um caminho e anote no README:

- **(a)** Demo com `teve_jogo` explícito no evento → é o que o Dataflow fará no
  Trabalho Final. Mais honesto e já suportado (`teve_jogo_origem: "informado"`).
- **(b)** Demo com data histórica dentro de janela real → caso 3 do Postman.
  Mostra a consulta funcionando de verdade.
- **(c)** Janelas de demonstração para o horário da apresentação, rotuladas
  como tal. Funciona, mas é dado inventado — se usar, diga na apresentação.

Recomendado: **(a) na narrativa, (b) no curl ao vivo.**

- [ ] decidido: ______________________

### 1.3 Testar local com o stub

```bash
cd api
pip install -r requirements-dev.txt
python scripts/criar_modelo_v0_stub.py --saida data/modelo_stub
pytest tests/ -q

MODEL_URI=data/modelo_stub/model.joblib uvicorn app.main:app --port 8080
```

**Pronto quando:** `curl localhost:8080/health` devolver `"status": "ok"` e
`"janelas_carregadas": 5404`.

- [ ] feito

### 1.4 Subir a branch

```bash
git checkout -b api-rest
git add api/
git commit -m "API REST de predicao de prisao com deploy no Cloud Run"
git push -u origin api-rest
```

Não espere estar tudo pronto para abrir o PR. Branch cedo evita conflito.

- [ ] feito

---

## 🔴 BLOCO 2 — Depende de outra pessoa (cobrar HOJE)

### 2.1 Mensagem para o responsável pelo modelo

> Pra API integrar eu preciso de três coisas:
> 1. O v0 em `gs://crimes-chicago-pdm-2026/models/prisao/v0/model.joblib`
> 2. Um `contrato_features.json` no mesmo diretório, com a lista de features na
>    ordem exata do treino
> 3. Qual versão do scikit-learn você usou — meu `requirements.txt` está
>    fixado em **1.9.1** e tem que ser a mesma. Versão diferente faz o pickle
>    carregar e prever errado **sem lançar erro**.
>
> Formato do contrato que a API espera:
> ```json
> {
>   "versao_modelo": "v0",
>   "alvo": "houve_prisao",
>   "sklearn_version": "1.9.1",
>   "features": [
>     {"nome": "tipo_crime",        "tipo": "categorica"},
>     {"nome": "local_ocorrencia",  "tipo": "categorica"},
>     {"nome": "distrito_policial", "tipo": "categorica"},
>     {"nome": "hora",              "tipo": "numerica"},
>     {"nome": "dia_semana",        "tipo": "numerica"},
>     {"nome": "mes",               "tipo": "numerica"},
>     {"nome": "eh_domestico",      "tipo": "booleana"},
>     {"nome": "teve_jogo",         "tipo": "booleana"}
>   ]
> }
> ```
> Se algum nome de coluna da `gold_treino_prisao` for diferente, me avisa —
> a API lê a lista do contrato, então não preciso mexer em código, só saber.

- [ ] enviado
- [ ] v0 publicado no GCS
- [ ] versão do sklearn confirmada: ______________
- [ ] nomes de coluna batem com o que a API monta

---

## 🔴 BLOCO 3 — Preparar o projeto (uma vez)

```bash
gcloud config set project pdm-crimes-chicago

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

PROJ_NUM=$(gcloud projects describe pdm-crimes-chicago --format='value(projectNumber)')
gcloud projects add-iam-policy-binding pdm-crimes-chicago \
  --member="serviceAccount:${PROJ_NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

O último comando é o que mais trava no primeiro deploy: sem ele o container
sobe, não consegue baixar o modelo do GCS, e o `/health` devolve 503.

- [ ] APIs habilitadas
- [ ] permissão no bucket concedida

---

## 🔴 BLOCO 4 — Deploy (depois que o v0 existir)

### 4.1 Publicar

```bash
cd api
./deploy.sh
```

O script roda os testes antes e **recusa** se o CSV de janelas tiver menos de
1.000 linhas, para não subir o arquivo de exemplo por engano.

**Pronto quando:** o script imprimir a URL e o `/health` responder 200.

- [ ] URL: ________________________________________

### 4.2 Medir latência contra o Cloud Run

```bash
./teste_latencia.sh "https://SUA-URL.run.app"
```

Salvar o print em `docs/evidencias/latencia_cloudrun.png` e atualizar a tabela
no fim do `README-api.md` com os números reais (os de lá são locais, com stub).

- [ ] medido — mediana: ______ ms

### 4.3 Atualizar a URL em dois lugares

- [ ] `README-api.md`, no topo
- [ ] `postman_collection.json`, variável `base_url`

### 4.4 Rodar a coleção do Postman inteira

Os 5 casos têm teste automático. Todos verdes.

- [ ] 5/5 passando

---

## 🔴 BLOCO 5 — Evidências

Em `api/docs/evidencias/`:

- [ ] `health.png` — `/health` com 200 e o modelo carregado
- [ ] `predict.png` — `/predict` com `prob_prisao`, versão e latência
- [ ] `predict_422.png` — entrada inválida recusada
- [ ] `latencia_cloudrun.png` — saída do `teste_latencia.sh`
- [ ] `postman.png` — os 5 casos verdes
- [ ] `cloudrun_console.png` — o serviço no ar no console

---

## 🔴 BLOCO 6 — README do grupo

Sua seção no `README.md` da raiz (não o `README-api.md`, que é o detalhado).
Precisa ter:

- [ ] O que a API faz, em dois parágrafos
- [ ] URL pública + um `curl` de exemplo que funciona copiando e colando
- [ ] Como rodar local
- [ ] **Justificativa de particionamento e processamento** — item cobrado nos
      critérios. A sua é: índice de janelas em memória em vez de consulta ao
      BigQuery por requisição, porque são 5.404 janelas e menos de 1 MB, e ir
      ao BigQuery adicionaria centenas de ms à latência que está sendo avaliada.
- [ ] Link para o `api/README-api.md`

---

## 🔴 BLOCO 7 — Apresentação

### 7.1 Seus slides (1 ou 2)

Sugestão de conteúdo, já que a apresentação vale 20%:

**Slide 1 — Arquitetura da API.** O caminho `Dataflow → POST /predict →
prob_prisao`, com os dois artefatos carregados no startup (modelo do GCS,
índice de janelas embarcado). Um número grande: a mediana de latência.

**Slide 2 — A decisão técnica.** Por que o índice fica em memória. É o slide
que responde "justificativa das escolhas técnicas de processamento", que está
nos critérios de avaliação.

- [ ] slides feitos e mandados para quem monta o deck

### 7.2 Ensaiar a sua parte (~1 min do roteiro)

Sequência exata:

```bash
curl -s $URL/health | jq
curl -s -X POST $URL/predict -H 'Content-Type: application/json' -d @exemplo.json | jq
./teste_latencia.sh $URL     # só a tabela final
```

- [ ] ensaiado, cabe em 1 min

### 7.3 No dia

```bash
./deploy.sh --aquecer   # ANTES — min-instances=1, mata o cold start
# ... apresentação ...
./deploy.sh --esfriar   # DEPOIS — volta para 0
```

⚠️ `--aquecer` passa a **cobrar mesmo parado**. Esfriar logo depois.

- [ ] aquecido antes
- [ ] **esfriado depois**

### 7.4 PR para a main

- [ ] PR aberto e aprovado

---

## Resumo do que trava o quê

```
1.1 janelas ─┐
             ├─► 4.1 deploy ─► 4.2 latência ─► 4.3 URL ─► 5 evidências ─► 6 README
2.1 modelo ──┘                                      │
3 permissões ┘                                      └─► 7.1 slides
```

O caminho crítico é o **modelo v0**. Tudo que não depende dele (1.1, 1.3, 1.4,
3, 7.1) dá para fechar hoje.
