"""Constantes do modelo de prisão."""
from __future__ import annotations

PROJETO = "pdm-crimes-chicago"
DATASET = "crimes_chicago"
REGIAO = "us-central1"
BUCKET = "crimes-chicago-pdm-2026"
TABELA_GOLD = f"{PROJETO}.{DATASET}.gold_treino_prisao"

EXPERIMENTO = "modelo-prisao-t2"
NOME_REGISTRY = "modelo-prisao"
ALIAS_CAMPEAO = "campeao"

SKLEARN_VERSAO = "1.9.1"
ALVO = "houve_prisao"

CATEGORICAS = ["tipo_crime", "local_ocorrencia", "distrito_policial", "hora", "dia_semana", "mes"]
BOOLEANAS = ["eh_domestico", "teve_jogo"]

# Ordem combinada com a API. Ela vai para o contrato_features.json.
FEATURES = [
    "tipo_crime",
    "local_ocorrencia",
    "distrito_policial",
    "hora",
    "dia_semana",
    "mes",
    "eh_domestico",
    "teve_jogo",
]

CONVENCOES = {
    "hora": "0-23, horario de parede de Chicago",
    "dia_semana": "1=domingo ... 7=sabado",
    "mes": "1-12",
    "teve_jogo": "mesmo distrito e janela_ini <= t < janela_fim, so em janelas de jogo",
    "texto": "tipo_crime e local_ocorrencia em UPPER(TRIM())",
}

V0_LINHAS = 10_000
SEMENTE = 42
