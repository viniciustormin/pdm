"""Consulta de `teve_jogo` em memória.

A gold_janelas do T1 tem 13.322 linhas e cerca de 1 MB, das quais 5.404 são
janelas de jogo. Isso cabe inteiro na memória do container, então a consulta é
feita local, sem ida ao BigQuery — o que mantém a latência do /predict na casa
dos microssegundos para esta parte.

Estrutura: por distrito, uma lista de janelas ordenada pelo início, mais um
prefixo de máximo do fim. Isso permite responder "existe janela cobrindo t?"
com busca binária mesmo quando as janelas se sobrepõem — e elas se sobrepõem,
porque doubleheaders da MLB geram duas janelas no mesmo estádio.
"""
from __future__ import annotations

import csv
import logging
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _parse_dt(texto: str) -> datetime:
    """Lê o DATETIME do BigQuery, que sai como 'YYYY-MM-DD HH:MM:SS' ou ISO."""
    texto = texto.strip().replace("T", " ")
    if "." in texto:
        texto = texto.split(".", 1)[0]
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


@dataclass
class _PorDistrito:
    inicios: list[datetime]
    fins: list[datetime]
    max_fim_ate: list[datetime]  # prefixo de máximo, alinhado com `inicios`
    ids: list[str]


class IndiceJanelas:
    """Índice de janelas de jogo, carregado uma vez no startup."""

    def __init__(self) -> None:
        self._por_distrito: dict[int, _PorDistrito] = {}
        self.total: int = 0
        self.origem: str | None = None
        self.min_data: datetime | None = None
        self.max_data: datetime | None = None

    # ------------------------------------------------------------------
    @classmethod
    def de_csv(cls, caminho: str | Path) -> "IndiceJanelas":
        caminho = Path(caminho)
        idx = cls()
        bruto: dict[int, list[tuple[datetime, datetime, str]]] = {}

        with caminho.open(newline="", encoding="utf-8") as fh:
            leitor = csv.DictReader(fh)
            obrigatorias = {"distrito_policial", "janela_ini", "janela_fim"}
            faltando = obrigatorias - set(leitor.fieldnames or [])
            if faltando:
                raise ValueError(
                    f"{caminho}: colunas ausentes no CSV de janelas: {sorted(faltando)}"
                )

            for linha in leitor:
                # O export deve conter só janelas de jogo, mas se vier a coluna
                # teve_jogo filtramos aqui também — defesa contra export errado.
                flag = (linha.get("teve_jogo") or "true").strip().lower()
                if flag in {"false", "f", "0"}:
                    continue
                distrito = int(float(linha["distrito_policial"]))
                ini = _parse_dt(linha["janela_ini"])
                fim = _parse_dt(linha["janela_fim"])
                if fim <= ini:
                    continue
                bruto.setdefault(distrito, []).append(
                    (ini, fim, linha.get("id_janela", ""))
                )

        for distrito, janelas in bruto.items():
            janelas.sort(key=lambda t: t[0])
            inicios = [j[0] for j in janelas]
            fins = [j[1] for j in janelas]
            ids = [j[2] for j in janelas]

            max_fim_ate: list[datetime] = []
            corrente = fins[0]
            for fim in fins:
                corrente = max(corrente, fim)
                max_fim_ate.append(corrente)

            idx._por_distrito[distrito] = _PorDistrito(inicios, fins, max_fim_ate, ids)
            idx.total += len(janelas)

        todos_ini = [d.inicios[0] for d in idx._por_distrito.values()]
        todos_fim = [d.max_fim_ate[-1] for d in idx._por_distrito.values()]
        idx.min_data = min(todos_ini) if todos_ini else None
        idx.max_data = max(todos_fim) if todos_fim else None
        idx.origem = str(caminho)
        return idx

    @classmethod
    def vazio(cls) -> "IndiceJanelas":
        return cls()

    # ------------------------------------------------------------------
    @property
    def distritos(self) -> list[int]:
        return sorted(self._por_distrito)

    def consultar(self, distrito: int, quando: datetime) -> tuple[bool, str | None]:
        """Retorna (teve_jogo, id_janela) para um instante local de Chicago.

        O intervalo é fechado no início e aberto no fim, igual ao da gold:
        janela_ini <= t < janela_fim.
        """
        dados = self._por_distrito.get(distrito)
        if dados is None:
            return False, None

        # Índice do último início <= quando.
        pos = bisect_right(dados.inicios, quando) - 1
        if pos < 0:
            return False, None

        # Com sobreposição, o prefixo de máximo diz se ALGUMA janela anterior
        # ainda está aberta neste instante.
        if dados.max_fim_ate[pos] <= quando:
            return False, None

        # Achar qual janela específica cobre, varrendo de trás para frente.
        # Na prática são 1 ou 2 iterações: o pior caso visto na gold é um
        # crime dentro de 3 janelas.
        for i in range(pos, -1, -1):
            if dados.fins[i] > quando >= dados.inicios[i]:
                return True, dados.ids[i] or None
            if dados.max_fim_ate[i] <= quando:
                break
        return False, None
