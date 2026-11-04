"""Pipelines do sklearn.

O pré-processamento fica dentro do Pipeline para a API só chamar predict_proba.
Use apenas classes do sklearn aqui: uma função própria dentro do Pipeline faria
o joblib depender deste pacote, que não existe na imagem da API.

Sem class_weight, porque a saída da API é uma probabilidade e reponderar as
classes distorceria esse valor.
"""
from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from config import BOOLEANAS, CATEGORICAS, SEMENTE

PARAMS_LOGREG = {"C": 1.0, "max_iter": 2000}
PARAMS_HGB = {"learning_rate": 0.1, "max_iter": 300, "max_leaf_nodes": 31, "early_stopping": False}
MIN_FREQUENCIA = 50
MIN_FREQUENCIA_V0 = 5


def construir_logreg(min_frequencia: int = MIN_FREQUENCIA) -> Pipeline:
    preprocessamento = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=min_frequencia), CATEGORICAS),
            ("bool", "passthrough", BOOLEANAS),
        ]
    )
    return Pipeline([("pre", preprocessamento), ("clf", LogisticRegression(**PARAMS_LOGREG))])


def construir_hgb(min_frequencia: int = MIN_FREQUENCIA) -> Pipeline:
    # Valor -1 representa categoria nova, que o HGB trata como ausente.
    # O limite de 255 categorias é o máximo aceito pelo HGB.
    preprocessamento = ColumnTransformer(
        [
            (
                "cat",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    min_frequency=min_frequencia,
                    max_categories=255,
                ),
                CATEGORICAS,
            ),
            ("bool", "passthrough", BOOLEANAS),
        ]
    )
    classificador = HistGradientBoostingClassifier(
        categorical_features=list(range(len(CATEGORICAS))),
        random_state=SEMENTE,
        **PARAMS_HGB,
    )
    return Pipeline([("pre", preprocessamento), ("clf", classificador)])
