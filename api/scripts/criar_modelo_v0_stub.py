#!/usr/bin/env python3
"""Gera um modelo STUB para desenvolver e testar a API antes do v0 real.

⚠️  NÃO É O MODELO DO TRABALHO. Ele é treinado em dados sintéticos e serve só
    para destravar a API enquanto o responsável pelo modelo não publica o
    gs://crimes-chicago-pdm-2026/models/prisao/v0/model.joblib.

    Quando o v0 real chegar, é só apontar o MODEL_URI para ele. O contrato
    gerado aqui tem o mesmo formato do que o treino real deve publicar.

Uso:
    python scripts/criar_modelo_v0_stub.py --saida data/modelo_stub
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: F401 (doc)
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAS = ["tipo_crime", "local_ocorrencia", "distrito_policial"]
NUMERICAS = ["hora", "dia_semana", "mes"]
BOOLEANAS = ["eh_domestico", "teve_jogo"]
FEATURES = CATEGORICAS + NUMERICAS + BOOLEANAS

TIPOS = ["THEFT", "BATTERY", "CRIMINAL DAMAGE", "ASSAULT", "NARCOTICS",
         "MOTOR VEHICLE THEFT", "BURGLARY", "ROBBERY", "DECEPTIVE PRACTICE",
         "WEAPONS VIOLATION", "CRIMINAL TRESPASS", "OTHER OFFENSE"]
LOCAIS = ["STREET", "RESIDENCE", "APARTMENT", "SIDEWALK", "PARKING LOT",
          "SMALL RETAIL STORE", "RESTAURANT", "BAR OR TAVERN"]
DISTRITOS = [1, 9, 12, 19]


def dados_sinteticos(n: int, seed: int = 42) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "tipo_crime": rng.choice(TIPOS, n),
            "local_ocorrencia": rng.choice(LOCAIS, n),
            "distrito_policial": rng.choice(DISTRITOS, n),
            "hora": rng.integers(0, 24, n),
            "dia_semana": rng.integers(1, 8, n),
            "mes": rng.integers(1, 13, n),
            "eh_domestico": rng.random(n) < 0.18,
            "teve_jogo": rng.random(n) < 0.30,
        }
    )
    # Relação inventada só para o modelo não ficar degenerado: narcóticos e
    # armas prendem muito mais (são categorias que só existem quando há
    # abordagem policial), madrugada prende um pouco mais.
    logito = (
        -2.2
        + 2.6 * df["tipo_crime"].isin(["NARCOTICS", "WEAPONS VIOLATION"])
        + 0.5 * df["tipo_crime"].eq("CRIMINAL TRESPASS")
        - 0.4 * df["tipo_crime"].isin(["THEFT", "BURGLARY"])
        + 0.3 * df["eh_domestico"]
        + 0.15 * df["teve_jogo"]
        + 0.02 * (df["hora"] - 12).abs()
    )
    p = 1 / (1 + np.exp(-logito))
    y = rng.random(n) < p
    return df[FEATURES], y.astype(bool)


def construir_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=5), CATEGORICAS),
            ("num", StandardScaler(), NUMERICAS),
            ("bool", "passthrough", BOOLEANAS),
        ],
        remainder="drop",
    )
    return Pipeline(
        [("pre", pre), ("clf", LogisticRegression(max_iter=1000, C=1.0))]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="data/modelo_stub")
    ap.add_argument("--n", type=int, default=20000)
    args = ap.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    X, y = dados_sinteticos(args.n)
    pipe = construir_pipeline().fit(X, y)

    import joblib

    joblib.dump(pipe, saida / "model.joblib")

    contrato = {
        "versao_modelo": "stub-dev",
        "alvo": "houve_prisao",
        "sklearn_version": sklearn.__version__,
        "treinado_em": "dados sinteticos - NAO USAR NA DEMO",
        "features": [
            *({"nome": c, "tipo": "categorica"} for c in CATEGORICAS),
            *({"nome": c, "tipo": "numerica"} for c in NUMERICAS),
            *({"nome": c, "tipo": "booleana"} for c in BOOLEANAS),
        ],
        "convencoes": {
            "dia_semana": "1=domingo ... 7=sabado (EXTRACT(DAYOFWEEK) do BigQuery)",
            "hora": "0-23, horario local de Chicago",
            "mes": "1-12",
        },
    }
    (saida / "contrato_features.json").write_text(
        json.dumps(contrato, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"modelo stub gerado em {saida.resolve()}")
    print(f"taxa de prisão nos dados sintéticos: {y.mean():.3f}")


if __name__ == "__main__":
    main()
