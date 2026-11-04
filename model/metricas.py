"""Métricas, baseline e escolha do campeão."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from config import ALVO

# Abaixo desta diferença de PR-AUC, os modelos são tratados como empatados.
EMPATE_PR_AUC = 0.001


def calcular(y_verdadeiro, probabilidades) -> dict[str, float]:
    y = np.asarray(y_verdadeiro).astype(int)
    p = np.clip(np.asarray(probabilidades, dtype=float), 1e-7, 1 - 1e-7)
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "prevalencia": float(y.mean()),
        # Com a taxa de prisão mudando entre os anos, esta média mostra o desvio de calibração.
        "media_prevista": float(p.mean()),
    }


class BaselinePorTipo:
    """Taxa de prisão por tipo de crime no treino. Tipo novo usa a taxa global."""

    def fit(self, treino: pd.DataFrame) -> "BaselinePorTipo":
        self.taxa_global_ = float(treino[ALVO].mean())
        self.taxas_ = treino.groupby("tipo_crime")[ALVO].mean().astype(float).to_dict()
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        return df["tipo_crime"].map(self.taxas_).fillna(self.taxa_global_).to_numpy(dtype=float)


def escolher_campeao(resultados: dict[str, dict[str, float]]) -> str:
    """Maior PR-AUC na validação. Em empate, menor log loss."""
    melhor_pr_auc = max(m["pr_auc"] for m in resultados.values())
    finalistas = {
        nome: m for nome, m in resultados.items()
        if melhor_pr_auc - m["pr_auc"] < EMPATE_PR_AUC
    }
    return min(finalistas, key=lambda nome: finalistas[nome]["log_loss"])


def supera_baseline(modelo: dict[str, float], baseline: dict[str, float]) -> bool:
    return modelo["pr_auc"] > baseline["pr_auc"] and modelo["log_loss"] < baseline["log_loss"]
