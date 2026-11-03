"""Contratos de entrada e saída da API.

A validação do Pydantic é o que devolve 422 quando o evento chega malformado —
exigência do item 3 da divisão de tarefas. Os campos espelham o evento que o
producer publica no Pub/Sub, menos `arrest`, que é justamente o alvo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Ocorrencia(BaseModel):
    """Uma ocorrência policial, no formato que o producer publica."""

    model_config = ConfigDict(
        extra="ignore",  # campos a mais no evento não derrubam a predição
        json_schema_extra={
            "examples": [
                {
                    "tipo_crime": "THEFT",
                    "local_ocorrencia": "STREET",
                    "distrito_policial": 19,
                    "data_hora_local_chicago": "2026-07-04T23:30:00",
                    "eh_domestico": False,
                }
            ]
        },
    )

    tipo_crime: Annotated[str, Field(min_length=1, max_length=120)]
    local_ocorrencia: Annotated[str, Field(min_length=1, max_length=120)]
    distrito_policial: Annotated[int, Field(ge=1, le=31)]

    # Horário de parede de Chicago. Sem offset, assume-se Chicago; com offset,
    # a API converte. Ver features.normalizar_para_chicago.
    data_hora_local_chicago: datetime

    eh_domestico: bool = False

    # Override opcional. Se vier preenchido, a API usa este valor e não consulta
    # o índice de janelas. É o caminho que o Dataflow do Trabalho Final usa,
    # quando ele já resolveu a janela antes de chamar a API.
    teve_jogo: bool | None = None

    # Só para rastreio ponta a ponta; não entra no modelo.
    unique_key: str | None = None


class LotePredicao(BaseModel):
    ocorrencias: Annotated[list[Ocorrencia], Field(min_length=1)]


class Predicao(BaseModel):
    prob_prisao: float = Field(description="Probabilidade de a ocorrência terminar em prisão")
    predicao: bool = Field(description="prob_prisao >= limiar configurado")
    limiar: float
    teve_jogo: bool
    teve_jogo_origem: Literal["informado", "consultado"]
    id_janela: str | None = None
    unique_key: str | None = None


class RespostaPredicao(Predicao):
    versao_modelo: str
    latencia_ms: float


class RespostaLote(BaseModel):
    versao_modelo: str
    total: int
    latencia_ms: float
    latencia_media_ms: float
    predicoes: list[Predicao]


class RespostaHealth(BaseModel):
    status: Literal["ok", "degradado"]
    modelo_carregado: bool
    janelas_carregadas: int
    servico: str
    revisao: str
    detalhe: str | None = None


class RespostaModelInfo(BaseModel):
    versao_modelo: str
    model_uri: str
    carregado_em: datetime
    sklearn_versao_treino: str | None
    sklearn_versao_runtime: str
    alvo: str
    features: list[str]
    limiar: float
    janelas: dict
