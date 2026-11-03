"""Carregamento do modelo e do contrato de features.

O modelo é carregado UMA vez, no startup (lifespan do FastAPI). Carregar a cada
request multiplicaria a latência por dez ou mais, e a latência vale 30% da nota
da aplicação ao vivo.

MODEL_URI aceita três formas:
  gs://bucket/caminho/model.joblib   -> baixa do GCS e guarda em cache local
  file:///caminho/model.joblib       -> caminho local explícito
  /caminho/model.joblib              -> caminho local

O contrato (contrato_features.json) é procurado no mesmo diretório do .joblib.
Ele é quem define a lista e a ordem das features — o código não tem essa lista
fixa, de propósito: quando o treino mudar as features, só o contrato muda.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import joblib
import numpy as np
import sklearn

log = logging.getLogger(__name__)

NOME_CONTRATO = "contrato_features.json"

# Usado só se o contrato não existir junto do modelo. Mantém a API de pé em
# desenvolvimento, mas o /model-info sinaliza que o contrato veio do padrão.
FEATURES_PADRAO = [
    "tipo_crime",
    "local_ocorrencia",
    "distrito_policial",
    "hora",
    "dia_semana",
    "mes",
    "eh_domestico",
    "teve_jogo",
]


@dataclass
class ModeloCarregado:
    estimador: object
    versao: str
    model_uri: str
    carregado_em: datetime
    features: list[str]
    alvo: str
    sklearn_versao_treino: str | None
    indice_classe_positiva: int
    contrato_do_padrao: bool

    def prever_proba(self, df) -> np.ndarray:
        """Probabilidade da classe positiva, uma por linha."""
        probs = self.estimador.predict_proba(df)
        return probs[:, self.indice_classe_positiva]


def _baixar_do_gcs(uri: str, destino: Path) -> Path:
    from google.cloud import storage  # import tardio: só quando é gs://

    partes = urlparse(uri)
    bucket_nome, blob_nome = partes.netloc, partes.path.lstrip("/")
    destino.parent.mkdir(parents=True, exist_ok=True)

    cliente = storage.Client()
    blob = cliente.bucket(bucket_nome).blob(blob_nome)
    blob.download_to_filename(str(destino))
    log.info("baixado de %s para %s (%s bytes)", uri, destino, destino.stat().st_size)
    return destino


def _resolver_local(uri: str, cache_dir: str) -> tuple[Path, Path | None]:
    """Devolve (caminho_do_modelo, caminho_do_contrato_ou_None)."""
    if uri.startswith("gs://"):
        cache = Path(cache_dir)
        modelo_local = cache / Path(urlparse(uri).path).name
        _baixar_do_gcs(uri, modelo_local)

        contrato_uri = uri.rsplit("/", 1)[0] + "/" + NOME_CONTRATO
        contrato_local = cache / NOME_CONTRATO
        try:
            _baixar_do_gcs(contrato_uri, contrato_local)
        except Exception as exc:  # noqa: BLE001 - contrato é opcional
            log.warning("contrato não encontrado em %s: %s", contrato_uri, exc)
            contrato_local = None
        return modelo_local, contrato_local

    caminho = Path(uri[7:] if uri.startswith("file://") else uri)
    contrato = caminho.parent / NOME_CONTRATO
    return caminho, (contrato if contrato.exists() else None)


def _indice_classe_positiva(estimador) -> int:
    """Descobre qual coluna de predict_proba é 'houve prisão'.

    Nunca assumir que é a coluna 1: depende de como o alvo foi codificado no
    treino. Se as classes forem [False, True] é 1; se forem [1, 0], é 0.
    """
    classes = list(getattr(estimador, "classes_", [0, 1]))
    for alvo in (True, 1, "1", "true", "True", "SIM", "Y"):
        if alvo in classes:
            return classes.index(alvo)
    # Sem classe positiva reconhecível, usa a última e registra o aviso.
    log.warning("classes_ do modelo não reconhecidas (%s); usando a última", classes)
    return len(classes) - 1


def carregar(model_uri: str, cache_dir: str) -> ModeloCarregado:
    caminho_modelo, caminho_contrato = _resolver_local(model_uri, cache_dir)
    if not caminho_modelo.exists():
        raise FileNotFoundError(f"modelo não encontrado: {caminho_modelo}")

    estimador = joblib.load(caminho_modelo)

    contrato: dict = {}
    contrato_do_padrao = True
    if caminho_contrato and caminho_contrato.exists():
        contrato = json.loads(caminho_contrato.read_text(encoding="utf-8"))
        contrato_do_padrao = False

    features = contrato.get("features") or FEATURES_PADRAO
    # O contrato pode listar strings ou objetos {"nome": ..., "tipo": ...}.
    features = [f["nome"] if isinstance(f, dict) else str(f) for f in features]

    versao = str(contrato.get("versao_modelo") or os.getenv("MODEL_VERSION") or "v0")
    treino_sk = contrato.get("sklearn_version")

    if treino_sk and treino_sk != sklearn.__version__:
        # Não derruba a API: avisa alto. Pickle de sklearn entre versões
        # diferentes pode carregar e prever errado em silêncio.
        log.warning(
            "VERSÃO DE SKLEARN DIVERGENTE: treino=%s runtime=%s",
            treino_sk,
            sklearn.__version__,
        )

    mc = ModeloCarregado(
        estimador=estimador,
        versao=versao,
        model_uri=model_uri,
        carregado_em=datetime.now(timezone.utc),
        features=features,
        alvo=str(contrato.get("alvo", "houve_prisao")),
        sklearn_versao_treino=treino_sk,
        indice_classe_positiva=_indice_classe_positiva(estimador),
        contrato_do_padrao=contrato_do_padrao,
    )
    log.info(
        "modelo %s carregado de %s com %d features",
        mc.versao,
        model_uri,
        len(mc.features),
    )
    return mc


def limpar_cache(cache_dir: str) -> None:
    shutil.rmtree(cache_dir, ignore_errors=True)
