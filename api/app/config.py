"""Configuração da API, toda por variável de ambiente.

Nada de valor fixo no código: o Cloud Run injeta as variáveis no deploy, e o
mesmo container roda em dev e em produção só trocando o ambiente.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

TZ_CHICAGO = ZoneInfo("America/Chicago")


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "t", "yes", "sim"}


@dataclass(frozen=True)
class Config:
    # Caminho do modelo. Aceita gs://..., file://... ou caminho local.
    # O contrato de features é procurado no MESMO diretório.
    model_uri: str = field(
        default_factory=lambda: os.getenv(
            "MODEL_URI",
            "gs://crimes-chicago-pdm-2026/models/prisao/v0/model.joblib",
        )
    )
    # Onde o modelo baixado do GCS fica em cache dentro do container.
    cache_dir: str = field(default_factory=lambda: os.getenv("CACHE_DIR", "/tmp/modelo"))

    # CSV com as janelas de jogo exportadas da gold_janelas (ver scripts/).
    janelas_csv: str = field(
        default_factory=lambda: os.getenv("JANELAS_CSV", "data/janelas_jogo.csv")
    )
    # Se o CSV não existir, a API sobe mesmo assim e responde teve_jogo=False.
    # Em produção isso deve ser False para o deploy falhar alto.
    janelas_opcional: bool = field(
        default_factory=lambda: _env_bool("JANELAS_OPCIONAL", True)
    )

    # Limite de itens no /predict/batch. Protege contra payload gigante.
    batch_max: int = field(default_factory=lambda: int(os.getenv("BATCH_MAX", "500")))

    # Limiar usado só para o campo booleano `predicao`. A probabilidade crua
    # continua sendo a saída principal.
    limiar: float = field(default_factory=lambda: float(os.getenv("LIMIAR", "0.5")))

    nome_servico: str = field(
        default_factory=lambda: os.getenv("K_SERVICE", "api-prisao-local")
    )
    revisao: str = field(default_factory=lambda: os.getenv("K_REVISION", "local"))


config = Config()
