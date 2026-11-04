"""Gravação local e envio ao GCS do modelo e do contrato."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn

from config import ALVO, BUCKET, CONVENCOES, FEATURES, SKLEARN_VERSAO

ARQUIVO_MODELO = "model.joblib"
ARQUIVO_CONTRATO = "contrato_features.json"


def conferir_sklearn() -> None:
    if sklearn.__version__ != SKLEARN_VERSAO:
        raise RuntimeError(
            f"scikit-learn {sklearn.__version__} instalado, mas a API usa {SKLEARN_VERSAO}. "
            "Instale model/requirements.txt."
        )


def montar_contrato(versao: str, algoritmo: str) -> dict:
    return {
        "versao_modelo": versao,
        "alvo": ALVO,
        "sklearn_version": sklearn.__version__,
        "features": FEATURES,
        "algoritmo": algoritmo,
        "treinado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "convencoes": CONVENCOES,
    }


def salvar(modelo, contrato: dict, destino: Path, metricas: dict | None = None) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, destino / ARQUIVO_MODELO)
    (destino / ARQUIVO_CONTRATO).write_text(
        json.dumps(contrato, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if metricas is not None:
        (destino / "metricas.json").write_text(
            json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return destino


def enviar_ao_gcs(origem: Path, versao: str, projeto: str, bucket: str = BUCKET) -> str:
    """Envia modelo e contrato para models/prisao/<versao>/ e devolve a pasta gs://."""
    from google.cloud import storage

    prefixo = f"models/prisao/{versao}"
    alvo = storage.Client(project=projeto).bucket(bucket)
    for nome in (ARQUIVO_MODELO, ARQUIVO_CONTRATO):
        arquivo = origem / nome
        if not arquivo.exists():
            raise FileNotFoundError(arquivo)
        alvo.blob(f"{prefixo}/{nome}").upload_from_filename(str(arquivo))
    return f"gs://{bucket}/{prefixo}"
