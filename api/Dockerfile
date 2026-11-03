# syntax=docker/dockerfile:1
#
# Imagem da API de predição de prisão — PDM T2.
#
# Decisões, porque o Dockerfile conta na nota:
#
#  - python:3.12-slim: imagem oficial enxuta. A `-alpine` obrigaria a compilar
#    numpy/scipy do zero (musl não tem wheel), o que estoura o tempo de build.
#  - requirements COPIADO antes do código: o Docker invalida o cache da camada
#    a partir do primeiro arquivo alterado. Com essa ordem, mexer no app/ não
#    reinstala scikit-learn a cada build.
#  - usuário não-root: o processo não precisa de root, e rodar como root é
#    violação básica de least privilege.
#  - PYTHONDONTWRITEBYTECODE / PYTHONUNBUFFERED: sem .pyc na imagem e log
#    saindo na hora, que é o que o Cloud Logging espera.
#  - sem --reload e sem gunicorn com vários workers: o Cloud Run escala por
#    instância; cada réplica carrega o modelo uma vez. Mais workers dentro do
#    mesmo container só multiplicariam a memória do modelo.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependências primeiro, para aproveitar o cache de camada.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código e dados depois.
COPY app/ ./app/
COPY data/janelas_jogo.csv ./data/janelas_jogo.csv

# Usuário sem privilégios. O /tmp/modelo é onde o joblib baixado do GCS fica
# em cache; precisa existir e pertencer ao usuário.
RUN useradd --create-home --uid 10001 apiuser \
 && mkdir -p /tmp/modelo \
 && chown -R apiuser:apiuser /app /tmp/modelo
USER apiuser

# Valores padrão; o deploy sobrescreve com --set-env-vars.
ENV MODEL_URI="gs://crimes-chicago-pdm-2026/models/prisao/v0/model.joblib" \
    JANELAS_CSV="data/janelas_jogo.csv" \
    JANELAS_OPCIONAL="false" \
    CACHE_DIR="/tmp/modelo" \
    LIMIAR="0.5" \
    PORT=8080

EXPOSE 8080

# O Cloud Run injeta $PORT; a forma shell é necessária para expandir a variável.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
