"""Fixtures dos testes.

O modelo usado aqui é o stub sintético (scripts/criar_modelo_v0_stub.py). Os
testes checam o CONTRATO e o comportamento da API, não a qualidade do modelo —
essa é responsabilidade de quem treina.
"""
from __future__ import annotations

import csv
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Janelas de teste, no formato exato do export do BigQuery.
# Distrito 19 (Wrigley) e 12 (United Center), com um par SOBREPOSTO de
# propósito no dia 2026-07-04 — é o caso do doubleheader, que o índice tem
# que resolver sem errar.
JANELAS = [
    # id_janela, distrito, ini, fim
    ("j1", 19, "2026-07-04 17:00:00", "2026-07-04 20:00:00"),
    ("j2", 19, "2026-07-04 18:30:00", "2026-07-04 21:30:00"),  # sobrepõe j1
    ("j3", 19, "2026-07-11 22:00:00", "2026-07-12 01:00:00"),  # vira o dia
    ("j4", 12, "2026-03-15 23:00:00", "2026-03-16 02:00:00"),
]


@pytest.fixture(scope="session")
def modelo_stub(tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("modelo")
    subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "criar_modelo_v0_stub.py"),
         "--saida", str(destino), "--n", "4000"],
        check=True, capture_output=True,
    )
    return destino / "model.joblib"


@pytest.fixture(scope="session")
def janelas_csv(tmp_path_factory) -> Path:
    caminho = tmp_path_factory.mktemp("janelas") / "janelas_jogo.csv"
    with caminho.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id_janela", "distrito_policial", "janela_ini", "janela_fim", "teve_jogo"])
        for linha in JANELAS:
            w.writerow([*linha, "true"])
    return caminho


@pytest.fixture(scope="session")
def client(modelo_stub, janelas_csv):
    os.environ["MODEL_URI"] = str(modelo_stub)
    os.environ["JANELAS_CSV"] = str(janelas_csv)
    os.environ["LIMIAR"] = "0.5"

    # Reimportar para que o Config leia as variáveis já definidas acima.
    import app.config
    importlib.reload(app.config)
    import app.main
    importlib.reload(app.main)

    with TestClient(app.main.app) as c:
        yield c


@pytest.fixture
def ocorrencia_base() -> dict:
    return {
        "tipo_crime": "THEFT",
        "local_ocorrencia": "STREET",
        "distrito_policial": 19,
        "data_hora_local_chicago": "2026-07-04T19:00:00",
        "eh_domestico": False,
    }
