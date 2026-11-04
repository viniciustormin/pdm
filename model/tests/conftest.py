"""Fixtures dos testes. A base é sintética e não mede a qualidade do modelo real."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ_MODELO = Path(__file__).resolve().parents[1]
RAIZ_REPO = RAIZ_MODELO.parent
sys.path.insert(0, str(RAIZ_MODELO))

TIPOS = ["THEFT", "BATTERY", "NARCOTICS", "ASSAULT", "ROBBERY", "WEAPONS VIOLATION"]
LOCAIS = ["STREET", "RESIDENCE", "APARTMENT", "SIDEWALK", "NAO_INFORMADO"]


def base_sintetica(linhas_por_ano: int = 5000, semente: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    partes = []
    for ano, split in [(2021, "TREINO"), (2022, "TREINO"), (2023, "TREINO"), (2024, "TREINO"),
                       (2025, "VALIDACAO"), (2026, "TESTE")]:
        n = linhas_por_ano
        df = pd.DataFrame(
            {
                "tipo_crime": rng.choice(TIPOS, n),
                "local_ocorrencia": rng.choice(LOCAIS, n),
                "distrito_policial": rng.choice([1, 9, 12, 19, 25], n),
                "hora": rng.integers(0, 24, n),
                "dia_semana": rng.integers(1, 8, n),
                "mes": rng.integers(1, 13, n),
                "eh_domestico": rng.random(n) < 0.2,
                "teve_jogo": rng.random(n) < 0.05,
                "ano": ano,
                "split": split,
            }
        )
        logito = -2.0 + 2.5 * df["tipo_crime"].isin(["NARCOTICS", "WEAPONS VIOLATION"]) \
            + 0.8 * (df["hora"].between(0, 4) & df["local_ocorrencia"].eq("STREET"))
        df["houve_prisao"] = rng.random(n) < 1 / (1 + np.exp(-logito))
        partes.append(df)
    return pd.concat(partes, ignore_index=True)


@pytest.fixture(scope="session")
def parquet(tmp_path_factory) -> Path:
    caminho = tmp_path_factory.mktemp("base") / "gold.parquet"
    base_sintetica().to_parquet(caminho)
    return caminho
