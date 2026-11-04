"""Leitura da gold_treino_prisao, com os tipos que a API envia ao modelo."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import ALVO, FEATURES, PROJETO, TABELA_GOLD, V0_LINHAS

COLUNAS = [*FEATURES, ALVO, "ano", "split"]
ANOS_POR_SPLIT = {
    "TREINO": {2021, 2022, 2023, 2024},
    "VALIDACAO": {2025},
    "TESTE": {2026},
}


def normalizar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Falha se houver nulo e deixa os tipos iguais aos de api/app/features.py."""
    faltando = [c for c in COLUNAS if c not in df.columns]
    if faltando:
        raise KeyError(f"colunas ausentes na base: {faltando}")

    nulos = df[COLUNAS].isna().sum()
    nulos = nulos[nulos > 0]
    if not nulos.empty:
        raise ValueError(f"valores nulos na base: {nulos.to_dict()}")

    saida = df[COLUNAS].copy()
    for coluna in ("tipo_crime", "local_ocorrencia", "split"):
        saida[coluna] = saida[coluna].astype(str)
    for coluna in ("distrito_policial", "hora", "dia_semana", "mes", "ano"):
        saida[coluna] = saida[coluna].astype("int64")
    for coluna in ("eh_domestico", "teve_jogo", ALVO):
        saida[coluna] = saida[coluna].astype(bool)
    return saida


def validar_splits(df: pd.DataFrame) -> None:
    """Garante que nenhum ano apareça fora do seu split."""
    for split, anos in df.groupby("split")["ano"].unique().items():
        if split not in ANOS_POR_SPLIT:
            raise ValueError(f"split desconhecido: {split}")
        fora = set(int(a) for a in anos) - ANOS_POR_SPLIT[split]
        if fora:
            raise ValueError(f"split {split} contém anos indevidos: {sorted(fora)}")


def _consultar(sql: str) -> pd.DataFrame:
    from google.cloud import bigquery

    cliente = bigquery.Client(project=PROJETO)
    return cliente.query(sql).to_dataframe(create_bqstorage_client=True)


def carregar_split(split: str, parquet: Path | None = None) -> pd.DataFrame:
    if parquet is not None:
        df = pd.read_parquet(parquet)
        df = df[df["split"] == split]
    else:
        lista = ", ".join(COLUNAS)
        df = _consultar(f"SELECT {lista} FROM `{TABELA_GOLD}` WHERE split = '{split}'")
    if df.empty:
        raise ValueError(f"split {split} sem linhas")
    df = normalizar_tipos(df)
    validar_splits(df)
    return df


def carregar_amostra_v0(parquet: Path | None = None, linhas: int = V0_LINHAS) -> pd.DataFrame:
    """Amostra reprodutível só do treino, sem tocar em validação e teste."""
    if parquet is not None:
        df = carregar_split("TREINO", parquet)
        if len(df) < linhas:
            raise ValueError(f"treino com {len(df)} linhas, menos que as {linhas} pedidas")
        return df.sample(n=linhas, random_state=42)

    lista = ", ".join(COLUNAS)
    df = _consultar(
        f"SELECT {lista} FROM `{TABELA_GOLD}` WHERE split = 'TREINO' "
        f"ORDER BY FARM_FINGERPRINT(CAST(unique_key AS STRING)) LIMIT {linhas}"
    )
    if len(df) < linhas:
        raise ValueError(f"treino com {len(df)} linhas, menos que as {linhas} pedidas")
    df = normalizar_tipos(df)
    validar_splits(df)
    return df
