"""Runner da versão agêntica do Agente 1 (T23j): roda os casos, um a um, e grava resultados e logs.

Tudo aqui é código determinístico. O LLM só decide dentro do `rodar_agente` (o rótulo, as ferramentas
e o reparo); este módulo prepara a cópia da API cobaia, roda o Maven antes e depois, confere o guarda
no arquivo final, trata os erros que atravessam o laço e grava o resultado de cada execução.

Separação exigida pelo CLAUDE.md: `executar_caso` recebe só o patch e o nome do teste afetado e nunca
vê o oráculo; o rótulo e a categoria entram no `registrar`, depois do caso.

Uso, na raiz do repositório (PyCharm: veja o README):

    python -m agente_contrato.rodar --api ../rest-test-healing-sut --saida resultados/NOME --orcamento-usd 0.10
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agente_contrato import cliente_claude, execucao, prompts
from agente_contrato.agentes import ResultadoAgente, rodar_agente
from agente_contrato.cliente_claude import ErroDeRede, ErroFatal, RespostaInvalida
from agente_contrato.ferramentas import guarda_do_caso, montar
from agente_contrato.registro import (NAO_REPARAR, REPARAR, Fim, caminho_do_agente, entrada_do_log,
                                      gravar_execucao, gravar_resultados, registrar, traduzir)
from agente_contrato.registro_llm import (LogDeChamadas, Orcamento, OrcamentoEsgotado, PromptAcimaDoLimite,
                                          gasto_do_log)
from agente_contrato.relogio import LIMITE_CASO_S, RelogioCaso
from agente_contrato.teste_java import texto_do_metodo

TAG = "linha-de-base-2"     # D72
REPETICOES = 3              # D92: 3 repetições por caso nos agentes
MAX_ERROS_LLM_SEGUIDOS = 3  # D104: valor inicial
RAIZ_REPO = Path(__file__).resolve().parent.parent

# Códigos de saída, iguais aos da v1: quem roda vê por que a rodada parou.
SAIDA_OK, SAIDA_ERRO_FATAL, SAIDA_ORCAMENTO, SAIDA_ERROS_SEGUIDOS, SAIDA_PROMPT_GRANDE = 0, 3, 4, 5, 6
SAIDA_NAO_CONGELADO = 7

ARQUIVO_RESULTADOS = "resultados-agente1.json"
ARQUIVO_CHAMADAS = "chamadas.jsonl"
ARQUIVO_LOG = "log-agentica.json"


# ---------------------------------------------------------------- casos (sem o rótulo do oráculo)

@dataclass(frozen=True)
class Caso:
    """O que o runner passa ao caso: só o patch e o teste afetado (D112). O oráculo fica de fora."""
    id_caso: str
    patch: Path
    classe: str
    metodo: str


def carregar_casos(oraculo: dict, raiz_repo: Path = RAIZ_REPO, ids: set[str] | None = None) -> list[Caso]:
    """Os casos em ordem fixa de `id_caso`, sem sorteio (D82)."""
    casos = []
    for c in sorted(oraculo["casos"], key=lambda c: c["id_caso"]):
        if ids and c["id_caso"] not in ids:
            continue
        classe, metodo = c["teste_afetado"].split(".")
        casos.append(Caso(c["id_caso"], (raiz_repo / c["patch"]).resolve(), classe, metodo))
    return casos


def arquivo_de_teste(raiz: Path, classe: str) -> str:
    """O caminho do arquivo da classe de teste, relativo à cópia; deve haver exatamente um. Igual à v1."""
    achados = list((raiz / "src" / "test" / "java").rglob(f"{classe}.java"))
    if len(achados) != 1:
        raise execucao.ErroDeExecucao(f"{classe}.java: {len(achados)} arquivos, esperado 1")
    return achados[0].relative_to(raiz).as_posix()
