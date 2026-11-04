#!/usr/bin/env python3
"""Publica o campeão no GCS e no Vertex AI Model Registry. Sem deploy e sem Endpoint.

A imagem informada em --container precisa ter o mesmo scikit-learn do treino.
Por isso o padrão do projeto é a imagem da própria API no Cloud Run:

  IMAGEM=$(gcloud run services describe api-prisao --region us-central1 \
    --format='value(spec.template.spec.containers[0].image)')
  python registrar.py --artefatos artefatos/completo --container "$IMAGEM"

Esse registro serve para versionamento. A rota /predict da API não usa o formato
{"instances": [...]} de um Endpoint do Vertex, e a predição acontece no Cloud Run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import artefatos as art
from config import ALIAS_CAMPEAO, NOME_REGISTRY, PROJETO, REGIAO


def ler_contrato(pasta: Path) -> dict:
    contrato = json.loads((pasta / art.ARQUIVO_CONTRATO).read_text(encoding="utf-8"))
    if contrato["sklearn_version"] != art.SKLEARN_VERSAO:
        raise RuntimeError(
            f"artefato treinado com scikit-learn {contrato['sklearn_version']}; "
            f"a API usa {art.SKLEARN_VERSAO}"
        )
    return contrato


def registrar(pasta: Path, container: str) -> str:
    from google.cloud import aiplatform
    from google.cloud.aiplatform.models import ModelRegistry

    contrato = ler_contrato(pasta)
    versao = contrato["versao_modelo"]
    pasta_gcs = art.enviar_ao_gcs(pasta, versao, PROJETO)

    aiplatform.init(project=PROJETO, location=REGIAO)
    existentes = aiplatform.Model.list(filter=f'display_name="{NOME_REGISTRY}"')
    pai = existentes[0].resource_name if existentes else None

    # Um alias aponta para uma versão só, então ele sai da versão anterior.
    if pai:
        registro = ModelRegistry(pai)
        for item in registro.list_versions():
            if ALIAS_CAMPEAO in (item.version_aliases or []):
                registro.remove_version_aliases([ALIAS_CAMPEAO], item.version_id)

    modelo = aiplatform.Model.upload(
        display_name=NOME_REGISTRY,
        artifact_uri=pasta_gcs,
        serving_container_image_uri=container,
        serving_container_predict_route="/predict",
        serving_container_health_route="/health",
        parent_model=pai,
        is_default_version=True,
        version_aliases=[ALIAS_CAMPEAO],
        version_description=f"{versao}: {contrato['algoritmo']}, sklearn {contrato['sklearn_version']}",
        labels={"alvo": "houve-prisao", "versao": versao},
    )
    print(f">> registrado: {modelo.resource_name} versão {modelo.version_id}")
    print(f">> para a API usar: MODEL_URI={pasta_gcs}/{art.ARQUIVO_MODELO} ./deploy.sh")
    return modelo.resource_name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--artefatos", type=Path, default=Path("artefatos/completo"))
    ap.add_argument("--container", required=True, help="imagem com o mesmo scikit-learn do treino")
    args = ap.parse_args()
    art.conferir_sklearn()
    registrar(args.artefatos, args.container)


if __name__ == "__main__":
    main()
