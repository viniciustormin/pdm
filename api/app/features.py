"""Montagem das features, no formato exato que o treino usou.

Este módulo é o ponto mais perigoso da API: se `hora`, `dia_semana` ou `mes`
forem calculados de um jeito diferente do treino, a API devolve números que
parecem bons e estão errados — training/serving skew clássico, sem erro nenhum.
Por isso a convenção está escrita aqui e repetida no teste.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import TZ_CHICAGO
from .janelas import IndiceJanelas
from .schemas import Ocorrencia


def normalizar_para_chicago(quando: datetime) -> datetime:
    """Devolve o horário de parede de Chicago, sem tzinfo.

    Sem offset, assume-se que já é Chicago (é o que o producer publica).
    Com offset, converte. O resultado é naive de propósito: as janelas da
    gold_janelas são DATETIME, também sem fuso, e comparar naive com aware
    levanta TypeError.
    """
    if quando.tzinfo is None:
        return quando
    return quando.astimezone(TZ_CHICAGO).replace(tzinfo=None)


def dia_semana_bq(quando: datetime) -> int:
    """1 = domingo ... 7 = sábado.

    Mesma convenção do EXTRACT(DAYOFWEEK) do BigQuery, que é como a
    gold_treino_prisao foi montada. isoweekday() dá 1=segunda..7=domingo;
    o resto por 7 joga domingo para 0 e o +1 reindexa a partir de 1.
    """
    return quando.isoweekday() % 7 + 1


def resolver_teve_jogo(
    oc: Ocorrencia, quando: datetime, indice: IndiceJanelas
) -> tuple[bool, str, str | None]:
    """Retorna (teve_jogo, origem, id_janela)."""
    if oc.teve_jogo is not None:
        return oc.teve_jogo, "informado", None
    achou, id_janela = indice.consultar(oc.distrito_policial, quando)
    return achou, "consultado", id_janela


def montar_linha(oc: Ocorrencia, quando: datetime, teve_jogo: bool) -> dict:
    """Uma linha de features, com os nomes de coluna do treino."""
    return {
        "tipo_crime": oc.tipo_crime.strip().upper(),
        "local_ocorrencia": oc.local_ocorrencia.strip().upper(),
        "distrito_policial": oc.distrito_policial,
        "hora": quando.hour,
        "dia_semana": dia_semana_bq(quando),
        "mes": quando.month,
        "eh_domestico": bool(oc.eh_domestico),
        "teve_jogo": bool(teve_jogo),
    }


def montar_dataframe(linhas: list[dict], colunas: list[str]) -> pd.DataFrame:
    """DataFrame com as colunas na ordem do contrato.

    Reindexar pela lista do contrato garante que a ordem das colunas seja a do
    treino, mesmo que alguém mude a ordem do dicionário acima. Coluna que o
    contrato pede e não foi montada vira erro explícito, não NaN silencioso.
    """
    df = pd.DataFrame(linhas)
    faltando = [c for c in colunas if c not in df.columns]
    if faltando:
        raise KeyError(f"features exigidas pelo contrato e não montadas: {faltando}")
    return df[colunas]
