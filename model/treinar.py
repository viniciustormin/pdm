#!/usr/bin/env python3
"""Treina o modelo de probabilidade de prisão.

  python treinar.py v0        10 mil linhas, LogReg, publica para a API integrar
  python treinar.py completo  LogReg e HGB no Vertex AI Experiments, escolhe o
                              campeão na validação e avalia no teste uma única vez

O modo completo grava o resultado em artefatos/completo. O registrar.py publica.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import artefatos as art
import dados
import metricas as mt
import pipelines as pp
from config import ALVO, EXPERIMENTO, FEATURES, PROJETO, REGIAO, V0_LINHAS


def _prob_prisao(modelo, df) -> "object":
    """Probabilidade da classe True, sem assumir a posição da coluna."""
    coluna = list(modelo.classes_).index(True)
    return modelo.predict_proba(df[FEATURES])[:, coluna]


def treinar_v0(parquet: Path | None, saida: Path, publicar: bool) -> dict:
    treino = dados.carregar_amostra_v0(parquet, V0_LINHAS)
    validacao = dados.carregar_split("VALIDACAO", parquet)

    modelo = pp.construir_logreg(pp.MIN_FREQUENCIA_V0).fit(treino[FEATURES], treino[ALVO])
    resultado = {
        "linhas_treino": len(treino),
        "linhas_validacao": len(validacao),
        "validacao": mt.calcular(validacao[ALVO], _prob_prisao(modelo, validacao)),
    }
    art.salvar(modelo, art.montar_contrato("v0", "logreg"), saida, resultado)

    if publicar:
        resultado["gcs"] = art.enviar_ao_gcs(saida, "v0", PROJETO)
    return resultado


def treinar_candidatos(treino, validacao) -> tuple[dict, dict, dict]:
    """Treina os dois modelos e calcula baseline e métricas de validação."""
    baseline = mt.BaselinePorTipo().fit(treino)
    metricas_baseline = mt.calcular(validacao[ALVO], baseline.prever(validacao))

    construtores = {"logreg": pp.construir_logreg, "hgb": pp.construir_hgb}
    modelos, resultados = {}, {}
    for nome, construir in construtores.items():
        print(f">> treinando {nome} com {len(treino)} linhas")
        modelos[nome] = construir().fit(treino[FEATURES], treino[ALVO])
        resultados[nome] = mt.calcular(validacao[ALVO], _prob_prisao(modelos[nome], validacao))
        print(f"   validação: {resultados[nome]}")
    return modelos, resultados, metricas_baseline


def _prefixar(metricas: dict, prefixo: str) -> dict:
    return {f"{prefixo}_{chave}": valor for chave, valor in metricas.items()}


def registrar_runs(resultados: dict, baseline: dict, linhas_treino: int, carimbo: str) -> dict:
    """Cria um run por modelo no Experiments e devolve os nomes dos runs."""
    from google.cloud import aiplatform

    aiplatform.init(
        project=PROJETO,
        location=REGIAO,
        experiment=EXPERIMENTO,
        experiment_tensorboard=False,
    )
    params = {"logreg": pp.PARAMS_LOGREG, "hgb": pp.PARAMS_HGB}
    runs = {}
    for nome, metricas_val in resultados.items():
        runs[nome] = f"{nome}-{carimbo}"
        with aiplatform.start_run(runs[nome]):
            aiplatform.log_params(
                {
                    "algoritmo": nome,
                    "linhas_treino": linhas_treino,
                    "split": "treino 2021-2024, validacao 2025, teste 2026",
                    "min_frequency": pp.MIN_FREQUENCIA,
                    **{k: str(v) for k, v in params[nome].items()},
                }
            )
            aiplatform.log_metrics(
                {**_prefixar(metricas_val, "val"), **_prefixar(baseline, "baseline_val")}
            )
    return runs


def registrar_teste(run: str, metricas_teste: dict, baseline_teste: dict) -> None:
    from google.cloud import aiplatform

    with aiplatform.start_run(run, resume=True):
        aiplatform.log_params({"campeao": "sim"})
        aiplatform.log_metrics(
            {**_prefixar(metricas_teste, "test"), **_prefixar(baseline_teste, "baseline_test")}
        )


def treinar_completo(parquet: Path | None, saida: Path, usar_vertex: bool, versao: str) -> dict:
    treino = dados.carregar_split("TREINO", parquet)
    validacao = dados.carregar_split("VALIDACAO", parquet)

    modelos, resultados, baseline_val = treinar_candidatos(treino, validacao)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    runs = registrar_runs(resultados, baseline_val, len(treino), carimbo) if usar_vertex else {}

    # A escolha termina antes de o teste ser lido.
    campeao = mt.escolher_campeao(resultados)
    teste = dados.carregar_split("TESTE", parquet)

    modelo = modelos[campeao]
    metricas_teste = mt.calcular(teste[ALVO], _prob_prisao(modelo, teste))
    baseline = mt.BaselinePorTipo().fit(treino)
    baseline_teste = mt.calcular(teste[ALVO], baseline.prever(teste))
    if usar_vertex:
        registrar_teste(runs[campeao], metricas_teste, baseline_teste)

    resultado = {
        "campeao": campeao,
        "linhas": {"treino": len(treino), "validacao": len(validacao), "teste": len(teste)},
        "validacao": resultados,
        "baseline_validacao": baseline_val,
        "teste": metricas_teste,
        "baseline_teste": baseline_teste,
        "supera_baseline_validacao": mt.supera_baseline(resultados[campeao], baseline_val),
        "supera_baseline_teste": mt.supera_baseline(metricas_teste, baseline_teste),
        "runs": runs,
    }
    art.salvar(modelo, art.montar_contrato(versao, campeao), saida, resultado)
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("modo", choices=["v0", "completo"])
    ap.add_argument("--saida", type=Path, help="padrão: artefatos/<modo>")
    ap.add_argument("--versao", default="v1", help="versão gravada no contrato do modo completo")
    ap.add_argument("--parquet", type=Path, help="lê a base de um arquivo, para testes locais")
    ap.add_argument("--sem-gcp", action="store_true", help="não usa GCS nem Experiments")
    args = ap.parse_args()

    art.conferir_sklearn()
    saida = args.saida or Path("artefatos") / args.modo

    if args.modo == "v0":
        resultado = treinar_v0(args.parquet, saida, publicar=not args.sem_gcp)
    else:
        resultado = treinar_completo(args.parquet, saida, not args.sem_gcp, args.versao)

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    print(f">> artefatos em {saida.resolve()}")


if __name__ == "__main__":
    main()
