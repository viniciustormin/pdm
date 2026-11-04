from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
import sklearn

from conftest import RAIZ_MODELO, RAIZ_REPO, base_sintetica

sys.path.insert(0, str(RAIZ_REPO / "api"))

import artefatos as art  # noqa: E402
import dados  # noqa: E402
import metricas as mt  # noqa: E402
import pipelines as pp  # noqa: E402
import treinar  # noqa: E402
from config import ALVO, FEATURES, SKLEARN_VERSAO  # noqa: E402


def _pins(caminho: Path) -> dict[str, str]:
    achados = re.findall(r"^([a-zA-Z0-9_-]+)==([^\s]+)", caminho.read_text(), flags=re.M)
    return dict(achados)


def test_versoes_iguais_as_da_api():
    api = _pins(RAIZ_REPO / "api" / "requirements.txt")
    modelo = _pins(RAIZ_MODELO / "requirements.txt")
    for pacote in ("scikit-learn", "joblib", "numpy", "pandas", "google-cloud-storage"):
        assert modelo[pacote] == api[pacote], pacote
    assert api["scikit-learn"] == SKLEARN_VERSAO == sklearn.__version__


def test_features_iguais_as_que_a_api_monta():
    from app.features import montar_linha
    from app.schemas import Ocorrencia

    oc = Ocorrencia(
        tipo_crime=" theft ",
        local_ocorrencia="street",
        distrito_policial=19,
        data_hora_local_chicago="2026-07-05T23:30:00",
    )
    linha = montar_linha(oc, oc.data_hora_local_chicago, True)
    assert list(linha) == FEATURES
    assert linha["tipo_crime"] == "THEFT"
    assert linha["dia_semana"] == 1  # 05/07/2026 é domingo, como no DAYOFWEEK do BigQuery


def test_campeao_usa_pr_auc_e_desempata_por_log_loss():
    assert mt.escolher_campeao({
        "a": {"pr_auc": 0.40, "log_loss": 0.30},
        "b": {"pr_auc": 0.50, "log_loss": 0.35},
    }) == "b"
    assert mt.escolher_campeao({
        "a": {"pr_auc": 0.5000, "log_loss": 0.30},
        "b": {"pr_auc": 0.5005, "log_loss": 0.35},
    }) == "a"


def test_baseline_e_taxa_por_tipo_com_fallback_global():
    treino = pd.DataFrame({"tipo_crime": ["A", "A", "B", "B"], ALVO: [True, False, False, False]})
    base = mt.BaselinePorTipo().fit(treino)
    previsto = base.prever(pd.DataFrame({"tipo_crime": ["A", "B", "NOVO"]}))
    assert list(previsto) == [0.5, 0.0, 0.25]


def test_rejeita_ano_fora_do_split():
    df = base_sintetica(10)
    df.loc[df["split"] == "TREINO", "ano"] = 2026
    with pytest.raises(ValueError, match="anos indevidos"):
        dados.validar_splits(dados.normalizar_tipos(df))


def test_rejeita_nulo():
    df = base_sintetica(10).astype({"local_ocorrencia": object})
    df.loc[0, "local_ocorrencia"] = None
    with pytest.raises(ValueError, match="nulos"):
        dados.normalizar_tipos(df)


def test_contrato_tem_o_formato_combinado(parquet, tmp_path):
    treinar.treinar_v0(parquet, tmp_path, publicar=False)
    contrato = json.loads((tmp_path / art.ARQUIVO_CONTRATO).read_text())
    assert contrato["versao_modelo"] == "v0"
    assert contrato["alvo"] == "houve_prisao"
    assert contrato["sklearn_version"] == SKLEARN_VERSAO
    assert contrato["features"] == FEATURES


def test_v0_nao_le_teste(parquet, tmp_path):
    with mock.patch.object(dados, "carregar_split", wraps=dados.carregar_split) as leitor:
        treinar.treinar_v0(parquet, tmp_path, publicar=False)
    splits = [chamada.args[0] for chamada in leitor.call_args_list]
    assert "TESTE" not in splits


def test_completo_escolhe_antes_de_ler_o_teste(parquet, tmp_path):
    ordem = []
    ler = dados.carregar_split
    escolher = mt.escolher_campeao

    def ler_com_registro(split, arquivo=None):
        ordem.append(split)
        return ler(split, arquivo)

    def escolher_com_registro(resultados):
        ordem.append("ESCOLHA")
        return escolher(resultados)

    with mock.patch.object(dados, "carregar_split", ler_com_registro), \
            mock.patch.object(mt, "escolher_campeao", escolher_com_registro):
        resultado = treinar.treinar_completo(parquet, tmp_path, usar_vertex=False, versao="v1")

    assert ordem == ["TREINO", "VALIDACAO", "ESCOLHA", "TESTE"]
    assert resultado["campeao"] in {"logreg", "hgb"}
    assert resultado["supera_baseline_validacao"] is True


def test_runs_do_experiments_sem_tensorboard(parquet, tmp_path):
    falso = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"google.cloud.aiplatform": falso}), \
            mock.patch("google.cloud.aiplatform", falso, create=True):
        resultado = treinar.treinar_completo(parquet, tmp_path, usar_vertex=True, versao="v1")

    assert falso.init.call_args.kwargs["experiment_tensorboard"] is False
    assert falso.start_run.call_count == 3  # dois runs e a retomada do campeão
    assert falso.start_run.call_args.kwargs == {"resume": True}
    assert falso.start_run.call_args.args[0] == resultado["runs"][resultado["campeao"]]
    nomes = [c.args[0] for c in falso.start_run.call_args_list]
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", n) for n in nomes)


@pytest.mark.parametrize("construir", [pp.construir_logreg, pp.construir_hgb])
def test_categoria_nova_nao_quebra(construir):
    df = dados.normalizar_tipos(base_sintetica(500))
    treino = df[df["split"] == "TREINO"]
    modelo = construir().fit(treino[FEATURES], treino[ALVO])
    novo = treino[FEATURES].head(2).copy()
    novo["tipo_crime"] = "CATEGORIA NOVA"
    novo["distrito_policial"] = 31
    probabilidades = modelo.predict_proba(novo)[:, 1]
    assert ((probabilidades > 0) & (probabilidades < 1)).all()


@pytest.mark.parametrize("modo", ["logreg", "hgb"])
def test_joblib_abre_na_api_sem_o_codigo_do_modelo(parquet, tmp_path, modo):
    """Abre o artefato em outro processo, só com a API no caminho, como no Cloud Run."""
    df = dados.carregar_split("TREINO", parquet)
    construir = {"logreg": pp.construir_logreg, "hgb": pp.construir_hgb}[modo]
    modelo = construir().fit(df[FEATURES], df[ALVO])
    art.salvar(modelo, art.montar_contrato("teste", modo), tmp_path)

    script = f"""
import sys
sys.path.insert(0, {str(RAIZ_REPO / 'api')!r})
from app import features as ft, modelo as md
from app.schemas import Ocorrencia
m = md.carregar({str(tmp_path / 'model.joblib')!r}, '/tmp/nao-usado')
oc = Ocorrencia(tipo_crime='narcotics', local_ocorrencia='street', distrito_policial=19,
                data_hora_local_chicago='2026-07-04T19:00:00', eh_domestico=False, teve_jogo=True)
linha = ft.montar_linha(oc, ft.normalizar_para_chicago(oc.data_hora_local_chicago), oc.teve_jogo)
p = m.prever_proba(ft.montar_dataframe([linha], m.features))
assert not m.contrato_do_padrao
assert m.features == {FEATURES!r}
assert m.indice_classe_positiva == 1
assert 0 < p[0] < 1
print(p[0])
"""
    ambiente = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    saida = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=ambiente, capture_output=True, text=True
    )
    assert saida.returncode == 0, saida.stderr


def test_registrar_sem_endpoint_e_com_alias(parquet, tmp_path):
    import registrar

    treinar.treinar_v0(parquet, tmp_path, publicar=False)
    falso = mock.MagicMock()
    falso.Model.list.return_value = []
    with mock.patch.dict(sys.modules, {
        "google.cloud.aiplatform": falso,
        "google.cloud.aiplatform.models": falso.models,
    }), mock.patch("google.cloud.aiplatform", falso, create=True), \
            mock.patch.object(art, "enviar_ao_gcs", return_value="gs://b/models/prisao/v0"):
        registrar.registrar(tmp_path, "imagem:1")

    argumentos = falso.Model.upload.call_args.kwargs
    assert argumentos["display_name"] == "modelo-prisao"
    assert argumentos["version_aliases"] == ["campeao"]
    assert argumentos["artifact_uri"] == "gs://b/models/prisao/v0"
    falso.Endpoint.create.assert_not_called()
    falso.Model.upload.return_value.deploy.assert_not_called()
