"""API REST de predição de prisão — PDM Trabalho 2.

Endpoints:
  GET  /health        liveness/readiness para o Cloud Run
  GET  /model-info    versão, origem e contrato do modelo em uso
  POST /predict       uma ocorrência -> prob_prisao
  POST /predict/batch várias ocorrências -> lista de prob_prisao

O modelo e o índice de janelas são carregados uma única vez no lifespan.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import sklearn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from . import features as ft
from . import modelo as md
from .config import config
from .janelas import IndiceJanelas
from .schemas import (
    LotePredicao,
    Ocorrencia,
    Predicao,
    RespostaHealth,
    RespostaLote,
    RespostaModelInfo,
    RespostaPredicao,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"severity":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
log = logging.getLogger("api-prisao")


class Estado:
    """Tudo que é carregado uma vez e reaproveitado entre requests."""

    modelo: md.ModeloCarregado | None = None
    janelas: IndiceJanelas = IndiceJanelas.vazio()
    erro_startup: str | None = None


estado = Estado()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- índice de janelas -------------------------------------------------
    caminho = Path(config.janelas_csv)
    if caminho.exists():
        try:
            estado.janelas = IndiceJanelas.de_csv(caminho)
            log.info(
                "janelas carregadas: %d em %d distritos (%s a %s)",
                estado.janelas.total,
                len(estado.janelas.distritos),
                estado.janelas.min_data,
                estado.janelas.max_data,
            )
        except Exception as exc:  # noqa: BLE001
            if not config.janelas_opcional:
                raise
            log.error("falha ao ler %s: %s — seguindo sem janelas", caminho, exc)
    elif config.janelas_opcional:
        log.warning(
            "arquivo de janelas %s não existe; teve_jogo será False quando não informado",
            caminho,
        )
    else:
        raise FileNotFoundError(f"JANELAS_CSV não encontrado: {caminho}")

    # --- modelo ------------------------------------------------------------
    # Falha aqui NÃO derruba o container: o /health passa a devolver 503 com o
    # motivo, o que é muito mais fácil de diagnosticar no Cloud Run do que um
    # container em crash loop.
    try:
        estado.modelo = md.carregar(config.model_uri, config.cache_dir)
    except Exception as exc:  # noqa: BLE001
        estado.erro_startup = f"{type(exc).__name__}: {exc}"
        log.error("falha ao carregar o modelo de %s: %s", config.model_uri, exc)

    yield
    log.info("encerrando")


app = FastAPI(
    title="API de predição de prisão — PDM T2",
    description=(
        "Serviço de inferência em tempo real. Recebe uma ocorrência policial de "
        "Chicago e devolve a probabilidade de ela terminar em prisão."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def _exigir_modelo() -> md.ModeloCarregado:
    if estado.modelo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"modelo não carregado: {estado.erro_startup}",
        )
    return estado.modelo


def _predizer(ocorrencias: list[Ocorrencia]) -> tuple[list[Predicao], md.ModeloCarregado]:
    modelo = _exigir_modelo()

    linhas, metadados = [], []
    for oc in ocorrencias:
        quando = ft.normalizar_para_chicago(oc.data_hora_local_chicago)
        teve_jogo, origem, id_janela = ft.resolver_teve_jogo(oc, quando, estado.janelas)
        linhas.append(ft.montar_linha(oc, quando, teve_jogo))
        metadados.append((teve_jogo, origem, id_janela, oc.unique_key))

    df = ft.montar_dataframe(linhas, modelo.features)
    probs = modelo.prever_proba(df)

    saida = [
        Predicao(
            prob_prisao=round(float(p), 6),
            predicao=bool(p >= config.limiar),
            limiar=config.limiar,
            teve_jogo=meta[0],
            teve_jogo_origem=meta[1],
            id_janela=meta[2],
            unique_key=meta[3],
        )
        for p, meta in zip(probs, metadados)
    ]
    return saida, modelo


# ---------------------------------------------------------------------------
@app.get("/health", response_model=RespostaHealth, tags=["infra"])
def health() -> JSONResponse:
    ok = estado.modelo is not None
    corpo = RespostaHealth(
        status="ok" if ok else "degradado",
        modelo_carregado=ok,
        janelas_carregadas=estado.janelas.total,
        servico=config.nome_servico,
        revisao=config.revisao,
        detalhe=None if ok else estado.erro_startup,
    )
    return JSONResponse(
        content=corpo.model_dump(),
        status_code=200 if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/model-info", response_model=RespostaModelInfo, tags=["infra"])
def model_info() -> RespostaModelInfo:
    modelo = _exigir_modelo()
    return RespostaModelInfo(
        versao_modelo=modelo.versao,
        model_uri=modelo.model_uri,
        carregado_em=modelo.carregado_em,
        sklearn_versao_treino=modelo.sklearn_versao_treino,
        sklearn_versao_runtime=sklearn.__version__,
        alvo=modelo.alvo,
        features=modelo.features,
        limiar=config.limiar,
        janelas={
            "total": estado.janelas.total,
            "distritos": estado.janelas.distritos,
            "origem": estado.janelas.origem,
            "cobertura_ini": str(estado.janelas.min_data) if estado.janelas.min_data else None,
            "cobertura_fim": str(estado.janelas.max_data) if estado.janelas.max_data else None,
            "contrato_do_padrao": modelo.contrato_do_padrao,
        },
    )


@app.post("/predict", response_model=RespostaPredicao, tags=["predicao"])
def predict(ocorrencia: Ocorrencia) -> RespostaPredicao:
    t0 = time.perf_counter()
    predicoes, modelo = _predizer([ocorrencia])
    latencia = (time.perf_counter() - t0) * 1000
    return RespostaPredicao(
        **predicoes[0].model_dump(),
        versao_modelo=modelo.versao,
        latencia_ms=round(latencia, 3),
    )


@app.post("/predict/batch", response_model=RespostaLote, tags=["predicao"])
def predict_batch(lote: LotePredicao) -> RespostaLote:
    n = len(lote.ocorrencias)
    if n > config.batch_max:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"lote de {n} itens acima do limite de {config.batch_max}",
        )
    t0 = time.perf_counter()
    predicoes, modelo = _predizer(lote.ocorrencias)
    latencia = (time.perf_counter() - t0) * 1000
    return RespostaLote(
        versao_modelo=modelo.versao,
        total=n,
        latencia_ms=round(latencia, 3),
        latencia_media_ms=round(latencia / n, 3),
        predicoes=predicoes,
    )


@app.middleware("http")
async def log_latencia(request: Request, call_next):
    t0 = time.perf_counter()
    resposta = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    resposta.headers["X-Latencia-Ms"] = f"{ms:.3f}"
    if request.url.path.startswith("/predict"):
        log.info("%s %s -> %s em %.2f ms", request.method, request.url.path,
                 resposta.status_code, ms)
    return resposta
