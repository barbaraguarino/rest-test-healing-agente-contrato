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


# ---------------------------------------------------------------- um caso: os 7 passos

@dataclass
class Execucao:
    """O que aconteceu numa execução (caso e repetição), antes de ler o oráculo."""
    fim: Fim
    compilou: bool | None = None
    passou: bool = False
    tempo_s: float = 0.0
    agente: ResultadoAgente | None = None  # None quando uma exceção interrompeu o agente
    antes: str = ""                        # o método afetado no começo do caso (para a T52)
    depois: str = ""                       # o método afetado no fim do caso
    detalhe: str | None = None             # por que o caso terminou em erro, para o log
    causa: str | None = None               # causa da exclusão (D111e): só em erro_execucao e erro_llm
    tentativas_maven_inicial: int = 0
    tentativas: int = 1                    # 2 quando houve reexecução por erro de rede (D104)


def _metodo(texto: str, metodo: str) -> str:
    try:
        return texto_do_metodo(texto, metodo)
    except ValueError:  # o método sumiu do arquivo: o log guarda o vazio, e a análise vê
        return ""


def executar_caso(caso: Caso, api: Path, tag: str, trabalho: Path, criar_modelo,
                  rodar=execucao.rodar_teste, limite_caso_s: float = LIMITE_CASO_S,
                  agora=time.monotonic) -> Execucao:
    """Os 7 passos de um caso: cópia, patch, Maven inicial, laço, guarda final, Maven final e o fim.

    Uma falha de infraestrutura sai como ErroDeExecucao; ErroDeRede, ErroFatal, PromptAcimaDoLimite e
    OrcamentoEsgotado atravessam para quem chama decidir (D104, D105, D106, D108). A cópia é apagada
    no fim, aconteça o que acontecer.
    """
    copia = execucao.preparar_copia(api, tag, trabalho)                          # 1
    try:
        execucao.aplicar_patch(copia, caso.patch)                                # 2
        arquivo = arquivo_de_teste(copia, caso.classe)
        original = (copia / arquivo).read_bytes().decode("utf-8")
        inicial, tentativas = execucao.rodar_teste_inicial(rodar, copia, caso.classe, caso.metodo)  # 3
        if inicial.passou:
            raise execucao.ErroDeExecucao(f"{caso.id_caso}: o teste afetado passa sem reparo",
                                          causa="teste_passa_sem_reparo")
        falha = execucao.ler_falha(copia / "target" / "surefire-reports")
        relogio = RelogioCaso(limite_caso_s, agora)  # D118: começa quando o agente recebe a falha
        inicio = agora()
        conferir = guarda_do_caso(copia, arquivo, caso.metodo)  # lê o original agora, antes do agente
        ferramentas = montar(copia, arquivo, caso.classe, caso.metodo, relogio, rodar)
        e = Execucao(Fim(NAO_REPARAR, None), antes=_metodo(original, caso.metodo),
                     tentativas_maven_inicial=tentativas)
        try:                                                                     # 4
            e.agente = rodar_agente(criar_modelo, ferramentas, relogio, arquivo, caso.classe, caso.metodo,
                                    falha, e.antes)
            e.fim = traduzir(e.agente)
        except RespostaInvalida as exc:  # D132: o caso termina; vale o reparo aceito, se já havia um
            mudou = (copia / arquivo).read_bytes().decode("utf-8") != original
            e.fim, e.detalhe = Fim(REPARAR if mudou else NAO_REPARAR, exc.codigo), exc.motivo
        final = (copia / arquivo).read_bytes().decode("utf-8")
        e.depois = _metodo(final, caso.metodo)
        if final != original:
            if e.fim.decisao != REPARAR:
                raise execucao.ErroDeExecucao(f"{caso.id_caso}: o arquivo mudou, mas a decisão é {e.fim.decisao}",
                                              causa="inconsistencia")
            veredito = conferir(final)                                           # 5: conferência (D129)
            if not veredito.aceito:
                raise execucao.ErroDeExecucao(f"{caso.id_caso}: o guarda recusou o arquivo final: "
                                              + "; ".join(veredito.motivos), causa="guarda_final")
        if e.fim.decisao == REPARAR and e.fim.erro != "timeout":                  # 6: Maven final
            e.compilou, e.passou, e.fim = _maven_final(rodar, copia, caso, relogio, e.fim)
        e.tempo_s = agora() - inicio  # da falha ao artefato final, com a espera do LLM, como na v1
        return e                                                                 # 7: quem chama grava
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def _maven_final(rodar, copia: Path, caso: Caso, relogio: RelogioCaso, fim: Fim) -> tuple[bool | None, bool, Fim]:
    """O Maven final com o menor entre 120 s e o que resta do caso (D111, D123); o estouro é `timeout` (D118)."""
    limite_s = relogio.limite_para_teste(execucao.LIMITE_TESTE_S)
    if limite_s <= 0:  # o caso já acabou: não há tempo para conferir o reparo
        return False, False, Fim(REPARAR, "timeout")
    try:
        r = execucao.rodar_teste_final(rodar, copia, caso.classe, caso.metodo, limite_s)
    except execucao.ErroDeExecucao as exc:
        if exc.codigo != "timeout":
            raise
        return False, False, Fim(REPARAR, "timeout")
    return r.compilou, r.passou, fim


def com_reexecucao(caso: Caso, repeticao: int, api: Path, tag: str, trabalho: Path, criar_fabrica,
                   rodar=execucao.rodar_teste, limite_caso_s: float = LIMITE_CASO_S,
                   agora=time.monotonic) -> Execucao:
    """D104: um erro de rede reexecuta o caso uma vez, do zero; se falhar de novo, `erro_llm`.

    Uma falha de infraestrutura vira `erro_execucao`, fora das métricas (D111e); o Maven inicial já
    tem a sua reexecução. `criar_fabrica(id_caso, repeticao)` devolve o `criar_modelo` da execução.
    """
    motivo = None
    for tentativa in (1, 2):
        try:
            e = executar_caso(caso, api, tag, trabalho / f"{caso.id_caso}-r{repeticao}-t{tentativa}",
                              criar_fabrica(caso.id_caso, repeticao), rodar, limite_caso_s, agora)
            e.tentativas = tentativa
            return e
        except ErroDeRede as exc:
            print(f"{caso.id_caso} r{repeticao}: erro de rede na tentativa {tentativa}: {exc.motivo}", flush=True)
            motivo = exc.motivo
        except execucao.ErroDeExecucao as exc:
            print(f"{caso.id_caso} r{repeticao}: ERRO {exc.codigo} ({exc.causa}): {exc}", flush=True)
            return Execucao(Fim(NAO_REPARAR, "erro_execucao"), detalhe=str(exc), causa=exc.causa,
                            tentativas=tentativa)
    return Execucao(Fim(NAO_REPARAR, "erro_llm"), detalhe=motivo, causa="erro_llm", tentativas=2)


# ---------------------------------------------------------------- orçamento

def com_trava(criar_modelo, orcamento: Orcamento):
    """Embrulha o `criar_modelo`: antes de cada chamada ao modelo, confere o orçamento (D105).

    O `ModeloClaude` não muda; a trava fica na porta, como o `Chamador` da v1.
    """
    def criar(sistema: str, definicoes: list[dict], formato: dict | None = None):
        modelo = criar_modelo(sistema, definicoes, formato=formato)

        def chamar(historico: list):
            orcamento.verificar()
            return modelo(historico)
        return chamar
    return criar
