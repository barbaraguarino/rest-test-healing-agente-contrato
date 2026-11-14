"""Runner do Agente 1 (T23j, T51): roda os casos, um a um, nos dois tratamentos, e grava resultados e logs.

Tudo aqui é código determinístico. O LLM só decide dentro do `rodar_agente` (o rótulo, as ferramentas
e o reparo); este módulo prepara a cópia da API cobaia, roda o Maven antes e depois, confere o guarda
no arquivo final, trata os erros que atravessam o laço e grava o resultado de cada execução. A baseline
(T51, D75) não usa LLM: `executar_baseline` faz os mesmos passos, com `baseline.reparar` no lugar do agente.

Separação exigida pelo CLAUDE.md: `executar_caso` recebe só o patch e o nome do teste afetado e nunca
vê o oráculo; o rótulo e a categoria entram no `registrar`, depois do caso.

Uso, na raiz do repositório (PyCharm: veja o README):

    python -m agente_contrato.rodar --api ../rest-test-healing-sut --saida resultados/NOME --orcamento-usd 0.10
    python -m agente_contrato.rodar ... --oraculo casos/oraculo-agente1-final.json   # o oráculo da T25
    python -m agente_contrato.rodar ... --saida resultados/NOME --retomar            # continua a rodada interrompida
    python -m agente_contrato.rodar --api ../rest-test-healing-sut --saida resultados/NOME --tratamentos baseline
                                                                     # só a baseline: sem chave, sem gasto
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agente_contrato import baseline, cliente_claude, execucao, prompts
from agente_contrato.agentes import ResultadoAgente, rodar_agente
from agente_contrato.cliente_claude import ErroDeRede, ErroFatal, RespostaInvalida
from agente_contrato.contrato import descrever_mudanca, diferenca, rotas_do_contrato
from agente_contrato.ferramentas import contratos, guarda_do_caso, montar
from agente_contrato.registro import (NAO_REPARAR, REPARAR, Fim, caminho_do_agente, entrada_do_log,
                                      gravar_execucao, gravar_resultados, registrar, traduzir)
from agente_contrato.registro_llm import (LogDeChamadas, Orcamento, OrcamentoEsgotado, PromptAcimaDoLimite,
                                          gasto_do_log, tratamento_da_linha)
from agente_contrato.relogio import LIMITE_CASO_S, RelogioCaso
from agente_contrato.teste_java import texto_do_metodo

TAG = "linha-de-base-2"     # D72
REPETICOES = 3              # D92: 3 repetições por caso nos agentes
REPETICOES_BASELINE = 1     # D92: 1 na baseline, que é determinística
MAX_ERROS_LLM_SEGUIDOS = 3  # D104: valor inicial
RAIZ_REPO = Path(__file__).resolve().parent.parent

# Códigos de saída, iguais aos da v1: quem roda vê por que a rodada parou.
SAIDA_OK, SAIDA_ERRO_FATAL, SAIDA_ORCAMENTO, SAIDA_ERROS_SEGUIDOS, SAIDA_PROMPT_GRANDE = 0, 3, 4, 5, 6
SAIDA_NAO_CONGELADO = 7

ARQUIVO_RESULTADOS = "resultados-agente1.json"
ARQUIVO_CHAMADAS = "chamadas.jsonl"
ARQUIVO_LOG = "log-agentica.json"
ORACULO_PADRAO = RAIZ_REPO / "casos" / "oraculo-agente1.json"  # o do piloto; o final é oraculo-agente1-final.json


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


# ---------------------------------------------------------------- a baseline num caso (T51)

@dataclass(frozen=True)
class DaBaseline:
    """O que explica a decisão da baseline, para o log: as mudanças aplicadas, as ignoradas (com o motivo)
    e os motivos do guarda, quando ele recusou o reparo."""
    aplicadas: tuple[str, ...] = ()
    ignoradas: tuple[tuple[str, str], ...] = ()
    recusas_do_guarda: tuple[str, ...] = ()


def executar_baseline(caso: Caso, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste,
                      limite_caso_s: float = LIMITE_CASO_S, agora=time.monotonic) -> tuple[Execucao, DaBaseline]:
    """Os passos de `executar_caso`, com a baseline (D75) no lugar do agente. Sem LLM.

    Cópia, patch e Maven inicial iguais aos dos agentes; a diferença do contrato vem da mesma função que a
    ferramenta ver_diferenca usa (`ferramentas.contratos`, T23d). O reparo passa pelo mesmo guarda
    (`guarda_do_caso`); recusado, não é gravado, e o caso termina sem reparo com o erro `guarda` (D74), como
    na v1. O Maven final é o dos agentes (D111, D118, D123). `tempo_s` conta da falha ao artefato final com
    o Maven final, como nos agentes (D133).
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
        relogio = RelogioCaso(limite_caso_s, agora)  # D118: começa quando a falha é recebida
        inicio = agora()
        conferir = guarda_do_caso(copia, arquivo, caso.metodo)
        antigo, novo = contratos(copia)
        mudancas = diferenca(antigo, novo)
        r = baseline.reparar(original, caso.metodo, mudancas, rotas_do_contrato(novo))  # 4: a regra
        e = Execucao(Fim(NAO_REPARAR, None), antes=_metodo(original, caso.metodo),
                     tentativas_maven_inicial=tentativas)
        recusas: tuple[str, ...] = ()
        if r.decisao == baseline.REPARAR:
            veredito = conferir(r.texto)                                         # 5: o guarda
            if veredito.aceito:
                (copia / arquivo).write_bytes(r.texto.encode("utf-8"))
                e.fim = Fim(REPARAR, None)
            else:
                e.fim, recusas = Fim(NAO_REPARAR, "guarda"), tuple(veredito.motivos)
        e.depois = _metodo((copia / arquivo).read_bytes().decode("utf-8"), caso.metodo)
        if e.fim.decisao == REPARAR:                                             # 6: Maven final
            e.compilou, e.passou, e.fim = _maven_final(rodar, copia, caso, relogio, e.fim)
        e.tempo_s = agora() - inicio  # D133: com o Maven final, como nos agentes
        da_baseline = DaBaseline(tuple(descrever_mudanca(m) for m in r.aplicadas),
                                 tuple((descrever_mudanca(m), motivo) for m, motivo in r.ignoradas), recusas)
        return e, da_baseline                                                    # 7: quem chama grava
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def baseline_do_caso(caso: Caso, repeticao: int, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste,
                     limite_caso_s: float = LIMITE_CASO_S, agora=time.monotonic) -> tuple[Execucao, DaBaseline]:
    """A baseline num caso; uma falha de infraestrutura vira `erro_execucao`, fora das métricas (D111e)."""
    try:
        return executar_baseline(caso, api, tag, trabalho / f"{caso.id_caso}-baseline-r{repeticao}", rodar,
                                 limite_caso_s, agora)
    except execucao.ErroDeExecucao as exc:
        print(f"{caso.id_caso} baseline r{repeticao}: ERRO {exc.codigo} ({exc.causa}): {exc}", flush=True)
        return Execucao(Fim(NAO_REPARAR, "erro_execucao"), detalhe=str(exc), causa=exc.causa), DaBaseline()


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


# ---------------------------------------------------------------- log e registro

TRATAMENTO = "agentes"  # o desta versão, igual ao que `registro.registrar` grava (D74)
BASELINE = "baseline"


def _entrada(caso: Caso, repeticao: int, e: Execucao, commits: tuple[str, str]) -> dict:
    """A entrada do log da execução; sem o resultado do agente (exceção no meio), os campos ficam nulos."""
    if e.agente is not None:
        entrada = entrada_do_log(caso.id_caso, repeticao, e.agente, e.fim, *commits)
    else:
        entrada = {"id_caso": caso.id_caso, "repeticao": repeticao, "motivo": None, "decisao": e.fim.decisao,
                   "erro": e.fim.erro, "rotulo_classifier": None, "justificativa": None, "detalhe": None,
                   "chamadas_classifier": None, "chamadas_repair": None, "recusas_do_guarda": [],
                   "commit_do_prompt": commits[0], "commit_do_codigo": commits[1]}
    entrada = {"id_caso": entrada["id_caso"], "tratamento": TRATAMENTO, **entrada}
    entrada.update(detalhe=entrada["detalhe"] or e.detalhe, causa=e.causa, tentativas=e.tentativas,
                   tentativas_maven_inicial=e.tentativas_maven_inicial, compilou=e.compilou, passou=e.passou,
                   tempo_s=round(e.tempo_s, 4))
    return entrada


def _entrada_baseline(caso: Caso, repeticao: int, e: Execucao, b: DaBaseline, commit_do_codigo: str) -> dict:
    """A entrada do log de uma execução da baseline: o que ela aplicou, o que ignorou e por quê (D89, D105).

    Sem prompt (`commit_do_prompt` nulo); o commit do código diz com que regra ela rodou.
    """
    return {"id_caso": caso.id_caso, "tratamento": BASELINE, "repeticao": repeticao, "decisao": e.fim.decisao,
            "erro": e.fim.erro, "aplicadas": list(b.aplicadas), "ignoradas": [list(x) for x in b.ignoradas],
            "recusas_do_guarda": list(b.recusas_do_guarda), "detalhe": e.detalhe, "causa": e.causa,
            "tentativas_maven_inicial": e.tentativas_maven_inicial, "compilou": e.compilou, "passou": e.passou,
            "tempo_s": round(e.tempo_s, 4), "commit_do_prompt": None, "commit_do_codigo": commit_do_codigo}


def exclusoes(entradas: list[dict]) -> dict:
    """Execuções fora das métricas (`erro_execucao` e `erro_llm`), com a causa e a contagem (D111e)."""
    lista = [{k: x[k] for k in ("id_caso", "tratamento", "repeticao", "erro", "causa")} for x in entradas
             if x["erro"] in ("erro_execucao", "erro_llm")]
    return {"exclusoes": lista, "exclusoes_por_causa": dict(Counter(x["causa"] for x in lista))}


def cabecalho(tag: str, oraculo: dict | None, commits: tuple[str, str], limite_caso_s: float) -> dict:
    """O que não pode mudar dentro de uma rodada, nem numa retomada (D105, D111, T53)."""
    return {"tag": tag, "oraculo": oraculo,
            "limites": {"teste_s": execucao.LIMITE_TESTE_S, "caso_s": limite_caso_s, "llm_s": cliente_claude.TIMEOUT_S},
            "commit_do_prompt": commits[0], "commit_do_codigo": commits[1]}


def _gravar_log(pasta: Path, cab: dict, sessoes: list[dict], entradas: list[dict]) -> None:
    dados = {**cab, "sessoes": sessoes, **exclusoes(entradas), "execucoes": entradas}
    (pasta / ARQUIVO_LOG).write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- retomada (T53, da v1 da T10)

class RetomadaInvalida(Exception):
    """A pasta de saída não pode receber esta rodada (D105: uma rodada, um oráculo, um prompt, um código)."""


def chave(x: dict) -> tuple[str, str, int]:
    """O que identifica uma execução na rodada: (caso, tratamento, repetição)."""
    return x["id_caso"], x["tratamento"], x["repeticao"]


@dataclass
class Anteriores:
    """O que as sessões anteriores da rodada já gravaram na pasta.

    Uma execução só está feita quando está nos resultados e no log: a queda entre gravar um e outro faz a
    execução rodar de novo. `linhas_de_chamadas`: quantas linhas o `chamadas.jsonl` tinha no começo
    desta sessão; o registro de uma execução só soma as linhas depois delas.
    """
    registros: list = field(default_factory=list)
    entradas: list = field(default_factory=list)
    sessoes: list = field(default_factory=list)
    chamadas_sem_registro: list = field(default_factory=list)  # pagas, de execuções que não chegaram ao fim
    linhas_de_chamadas: int = 0

    def feitos(self) -> set:
        return {chave(x) for x in self.entradas}


def _ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else None


def _sem_registro(linhas: list[str], feitos: set) -> list[dict]:
    """As chamadas pagas destas linhas cuja execução não está feita: o registro de ninguém as soma.

    Cada linha diz o tratamento (T49); as gravadas antes da T49 não têm o campo e são dos agentes.
    """
    contagem: dict = {}
    for linha in linhas:
        if not linha.strip():
            continue
        c = json.loads(linha)
        k = (c["id_caso"], tratamento_da_linha(c), c["repeticao"])
        if k in feitos:
            continue
        n, custo = contagem.get(k, (0, 0.0))
        contagem[k] = n + 1, custo + (c["custo_usd"] or 0)
    return [{"id_caso": i, "tratamento": t, "repeticao": r, "chamadas": n, "custo_usd": round(custo, 8)}
            for (i, t, r), (n, custo) in contagem.items()]


def carregar_anteriores(pasta: Path, retomar: bool, cab: dict) -> Anteriores:
    """Sem `retomar`, exige pasta sem rodada. Com `retomar`, devolve o que já foi gravado, e recusa se mudou
    a tag, o oráculo, os prompts, o código ou os limites (`cab`, de `cabecalho`). Não lê a chave da API.
    """
    resultados, log_rodada, chamadas = pasta / ARQUIVO_RESULTADOS, pasta / ARQUIVO_LOG, pasta / ARQUIVO_CHAMADAS
    if not retomar:
        if any(a.exists() for a in (resultados, log_rodada, chamadas)):
            raise RetomadaInvalida(f"{pasta} já tem uma rodada; use --retomar para continuá-la ou escolha outra "
                                   f"--saida")
        return Anteriores()
    dados, log = _ler_json(resultados), _ler_json(log_rodada)
    if log is None:
        if dados is not None or chamadas.exists():
            raise RetomadaInvalida(f"{pasta} tem resultados ou chamadas, mas não tem o {ARQUIVO_LOG}: não dá para "
                                   f"conferir com que oráculo, prompts, código e limites a rodada começou")
        return Anteriores()  # pasta vazia: a retomada começa do zero
    diferencas = [f"{k}: gravado {log.get(k)}, agora {v}" for k, v in cab.items() if log.get(k) != v]
    if dados is not None and dados["versao_api"] != cab["tag"]:
        diferencas.append(f"versao_api dos resultados: gravada {dados['versao_api']}, agora {cab['tag']}")
    if diferencas:
        raise RetomadaInvalida("a rodada gravada é de outra configuração (" + "; ".join(diferencas) + ")")
    no_resultado = {chave(r) for r in (dados or {"execucoes": []})["execucoes"]}
    a = Anteriores(entradas=[x for x in log["execucoes"] if chave(x) in no_resultado], sessoes=log["sessoes"])
    feitos = a.feitos()
    a.registros = [r for r in (dados or {"execucoes": []})["execucoes"] if chave(r) in feitos]
    linhas = chamadas.read_text(encoding="utf-8").splitlines() if chamadas.exists() else []
    a.linhas_de_chamadas = len(linhas)
    # cada linha é contada uma vez só: a desta sessão olha as linhas da sessão anterior; as de antes dela
    # já estão no registro de uma execução ou nas `chamadas_sem_registro` de uma sessão anterior
    desde = a.sessoes[-1]["linhas_de_chamadas_no_inicio"] if a.sessoes else 0
    a.chamadas_sem_registro = _sem_registro(linhas[desde:], feitos)
    return a


# ---------------------------------------------------------------- rodada

def aquecer(caso: Caso, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste) -> dict:
    """D111f: uma execução do Maven na tag limpa, sem patch, antes do primeiro caso. Fora das métricas.

    Um erro aqui não para a rodada: o Maven inicial de cada caso tem as próprias travas.
    """
    dados = {"teste": f"{caso.classe}.{caso.metodo}", "passou": None, "duracao_maven_s": None, "erro": None}
    try:
        copia = execucao.preparar_copia(api, tag, trabalho)
        r = rodar(copia, caso.classe, caso.metodo, execucao.LIMITE_TESTE_S)
        dados.update(passou=r.passou, duracao_maven_s=round(r.duracao_maven_s, 2))
    except execucao.ErroDeExecucao as exc:
        dados["erro"] = f"{exc.codigo} ({exc.causa}): {exc}"
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    return dados



# D82: em cada caso, a baseline e depois os agentes.
ORDEM_DOS_TRATAMENTOS = (BASELINE, TRATAMENTO)


def repeticoes_do(tratamento: str, repeticoes: int) -> int:
    """D92: 1 repetição na baseline, que é determinística; `repeticoes` nos agentes."""
    return REPETICOES_BASELINE if tratamento == BASELINE else repeticoes


def executar_rodada(casos: list[Caso], oraculo_por_id: dict, api: Path, tag: str, pasta: Path, repeticoes: int,
                    criar_fabrica, commits: tuple[str, str], rodar=execucao.rodar_teste,
                    aquecer_antes: bool = True, limite_caso_s: float = LIMITE_CASO_S,
                    agora=time.monotonic, oraculo: dict | None = None, anteriores: Anteriores | None = None,
                    tratamentos: tuple[str, ...] = ORDEM_DOS_TRATAMENTOS) -> int:
    """Roda caso a caso, na ordem da D82, e grava, depois de cada execução, os resultados e o log.

    Devolve o código de saída. `criar_fabrica(id_caso, repeticao)` devolve o `criar_modelo` de uma
    execução: o Claude com a trava de orçamento, ou o LLM simulado do ensaio. `commits`: os de
    `prompts/` e de `agente_contrato/` (D105). `oraculo`: o arquivo e o commit do oráculo (`oraculo_do_log`).
    `anteriores`: o que a rodada já gravou (`carregar_anteriores`), que é pulado (T53). Cada vez que o
    comando roda vira uma entrada de `sessoes` no log. `tratamentos`: quais rodam, sempre na ordem da D82;
    só com a baseline, `criar_fabrica` não é usado e nada chama o LLM. `repeticoes` vale para os agentes; a
    baseline roda 1 vez (D92).
    """
    anteriores = anteriores or Anteriores()
    feitos = anteriores.feitos()
    cab = cabecalho(tag, oraculo, commits, limite_caso_s)
    registros, entradas, sessoes = list(anteriores.registros), list(anteriores.entradas), list(anteriores.sessoes)
    seguidos = 0
    pasta.mkdir(parents=True, exist_ok=True)
    chamadas = pasta / ARQUIVO_CHAMADAS
    rodam = [t for t in ORDEM_DOS_TRATAMENTOS if t in tratamentos]
    pendentes = [(c, t, r) for c in casos for t in rodam for r in range(1, repeticoes_do(t, repeticoes) + 1)
                 if (c.id_caso, t, r) not in feitos]
    print(f"limites: teste {execucao.LIMITE_TESTE_S} s, caso {limite_caso_s:g} s, chamada ao LLM "
          f"{cliente_claude.TIMEOUT_S} s (D111) | prompts {commits[0]} | código {commits[1]}", flush=True)
    if oraculo:
        print(f"oráculo: {oraculo['arquivo']} (commit {oraculo['commit']})", flush=True)
    if feitos:
        sem = anteriores.chamadas_sem_registro
        print(f"retomada: {len(feitos)} execuções já gravadas, {len(pendentes)} a rodar; chamadas pagas sem "
              f"registro: {sum(c['chamadas'] for c in sem)} (US$ {sum(c['custo_usd'] for c in sem):.6f})",
              flush=True)
    if not pendentes:
        print("nada a rodar: todas as execuções já estão gravadas", flush=True)
        return SAIDA_OK
    sessao = {"inicio_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "repeticoes": repeticoes,
              "tratamentos": rodam,
              "execucoes_ja_gravadas": len(feitos), "linhas_de_chamadas_no_inicio": anteriores.linhas_de_chamadas,
              "chamadas_sem_registro": anteriores.chamadas_sem_registro, "aquecimento": None}
    sessoes.append(sessao)
    with tempfile.TemporaryDirectory(prefix="agentica-") as trabalho:
        if aquecer_antes:
            sessao["aquecimento"] = a = aquecer(pendentes[0][0], api, tag, Path(trabalho) / "aquecimento", rodar)
            print(f"aquecimento do Maven (D111f, fora das métricas): {a['teste']} passou={a['passou']} "
                  f"maven={a['duracao_maven_s']} s erro={a['erro']}", flush=True)
        _gravar_log(pasta, cab, sessoes, entradas)
        for caso in casos:
            for tratamento in rodam:
                for repeticao in range(1, repeticoes_do(tratamento, repeticoes) + 1):
                    if (caso.id_caso, tratamento, repeticao) in feitos:
                        continue
                    if tratamento == BASELINE:  # sem LLM: nada a reexecutar nem a cobrar (D75)
                        e, b = baseline_do_caso(caso, repeticao, api, tag, Path(trabalho), rodar, limite_caso_s,
                                                agora)
                        registro = registrar(e.fim, oraculo_por_id[caso.id_caso], repeticao, e.compilou, e.passou,
                                             e.tempo_s, tratamento=BASELINE, versao_agente=None)
                        entrada = _entrada_baseline(caso, repeticao, e, b, commits[1])
                        registros.append(registro)
                        entradas.append(entrada)
                        gravar_resultados(pasta / ARQUIVO_RESULTADOS, tag, registros)
                        gravar_execucao(pasta / "execucoes" / f"{caso.id_caso}-baseline-r{repeticao}", entrada, [],
                                        e.antes, e.depois)
                        _gravar_log(pasta, cab, sessoes, entradas)
                        print(f"{caso.id_caso} baseline r{repeticao}: decisao={registro['decisao']} "
                              f"compilou={registro['compilou']} passou={registro['passou']} erro={registro['erro']}",
                              flush=True)
                        continue  # a contagem de erro_llm seguidos é só dos agentes (D104)
                    try:
                        e = com_reexecucao(caso, repeticao, api, tag, Path(trabalho), criar_fabrica, rodar,
                                           limite_caso_s, agora)
                    except ErroFatal as exc:
                        print(f"PARADA: erro que repetir não resolve (D104, D108): {exc.motivo}", file=sys.stderr)
                        return SAIDA_ERRO_FATAL
                    except OrcamentoEsgotado as exc:
                        print(f"PARADA: {exc} (D105)", file=sys.stderr)
                        return SAIDA_ORCAMENTO
                    except PromptAcimaDoLimite as exc:
                        print(f"PARADA: {exc} (D106)", file=sys.stderr)
                        return SAIDA_PROMPT_GRANDE
                    # só as chamadas desta sessão: as de uma tentativa interrompida antes ficam sem registro
                    custo, tokens = gasto_do_log(chamadas, caso.id_caso, repeticao, anteriores.linhas_de_chamadas)
                    registro = registrar(e.fim, oraculo_por_id[caso.id_caso], repeticao, e.compilou, e.passou,
                                         e.tempo_s, tokens, round(custo, 8))
                    entrada = _entrada(caso, repeticao, e, commits)
                    registros.append(registro)
                    entradas.append(entrada)
                    gravar_resultados(pasta / ARQUIVO_RESULTADOS, tag, registros)
                    gravar_execucao(pasta / "execucoes" / f"{caso.id_caso}-r{repeticao}", entrada,
                                    caminho_do_agente(e.agente) if e.agente else [], e.antes, e.depois)
                    _gravar_log(pasta, cab, sessoes, entradas)
                    print(f"{caso.id_caso} agentes r{repeticao}: decisao={registro['decisao']} "
                          f"compilou={registro['compilou']} passou={registro['passou']} erro={registro['erro']} "
                          f"tokens={tokens} custo=US$ {custo:.6f} (rodada: US$ {gasto_do_log(chamadas)[0]:.6f})",
                          flush=True)
                    seguidos = seguidos + 1 if e.fim.erro == "erro_llm" else 0
                    if seguidos >= MAX_ERROS_LLM_SEGUIDOS:
                        print(f"PARADA: {seguidos} erro_llm seguidos (D104)", file=sys.stderr)
                        return SAIDA_ERROS_SEGUIDOS
    fora = exclusoes(entradas)
    contagem = ", ".join(f"{c}: {n}" for c, n in fora["exclusoes_por_causa"].items()) or "nenhuma"
    print(f"exclusões (fora das métricas): {len(fora['exclusoes'])} ({contagem})", flush=True)
    return SAIDA_OK


# ---------------------------------------------------------------- linha de comando

def commits_atuais() -> tuple[str, str]:
    """Os commits de `prompts/` e de `agente_contrato/`, com `+alterado` se há mudança pendente (D105)."""
    return prompts.commit_dos_prompts(), prompts.commit_dos_prompts(Path(__file__).resolve().parent)


class OraculoInvalido(Exception):
    """O arquivo do oráculo não pode ser usado: fora do repositório ou com mudança não gravada."""


def oraculo_do_log(arquivo: Path, raiz_repo: Path = RAIZ_REPO) -> dict:
    """O arquivo do oráculo, relativo à raiz do repositório, e o commit dele, para o log da sessão (T53).

    Como os prompts e o código (D105), o oráculo de uma rodada tem de estar gravado num commit: fora do
    repositório ou com mudança pendente, o resultado não diria com que oráculo rodou.
    """
    caminho = arquivo.resolve()
    try:
        relativo = caminho.relative_to(raiz_repo.resolve()).as_posix()
    except ValueError:
        raise OraculoInvalido(f"o oráculo {caminho} está fora do repositório") from None
    if not caminho.is_file():
        raise OraculoInvalido(f"o oráculo {relativo} não existe")
    commit = prompts.commit_dos_prompts(caminho)
    if commit.endswith(prompts.SUFIXO_ALTERADO) or commit == "sem-commit":
        raise OraculoInvalido(f"o oráculo {relativo} tem mudança não gravada ({commit}); grave antes de rodar")
    return {"arquivo": relativo, "commit": commit}


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", required=True, type=Path, help="clone da API cobaia (rest-test-healing-sut)")
    ap.add_argument("--saida", required=True, type=Path,
                    help="pasta de saída, nova ou vazia; com --retomar, a da rodada interrompida")
    ap.add_argument("--retomar", action="store_true",
                    help="continua a rodada interrompida na mesma --saida, sem refazer o que já foi gravado (T53)")
    ap.add_argument("--orcamento-usd", type=float,
                    help="obrigatório com os agentes: a rodada para quando o gasto do chamadas.jsonl da pasta chegar "
                         "a este valor (D105); na retomada, vale para a rodada inteira, somando as sessões anteriores")
    ap.add_argument("--tratamentos", nargs="+", choices=ORDEM_DOS_TRATAMENTOS, default=list(ORDEM_DOS_TRATAMENTOS),
                    help="quais tratamentos rodam, sempre na ordem da D82 (padrão: baseline e agentes); só com a "
                         "baseline, a rodada não lê a chave nem gasta nada")
    ap.add_argument("--repeticoes", type=int, default=REPETICOES,
                    help="repetições por caso nos agentes (D92: 3); a baseline roda 1 vez")
    ap.add_argument("--oraculo", type=Path, default=ORACULO_PADRAO,
                    help="arquivo do oráculo, dentro do repositório (padrão: casos/oraculo-agente1.json, o do "
                         "piloto; o da T25 é casos/oraculo-agente1-final.json)")
    ap.add_argument("--casos", nargs="*", help="ids dos casos (padrão: todos os do oráculo)")
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--env", type=Path, help="arquivo .env com a chave (padrão: .env na raiz do repositório)")
    ap.add_argument("--sim", action="store_true", help="não pedir a confirmação antes de gastar")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, sdk=None, rodar=execucao.rodar_teste) -> int:
    """Roda a versão agêntica com o Claude de verdade. `sdk` e `rodar` são injetáveis só nos testes."""
    args = _argumentos(argv)
    com_agentes = TRATAMENTO in args.tratamentos
    if com_agentes and args.orcamento_usd is None:
        print("com os agentes, --orcamento-usd é obrigatório (D105)", file=sys.stderr)
        return 2
    try:
        do_oraculo = oraculo_do_log(args.oraculo)
    except OraculoInvalido as exc:
        print(exc, file=sys.stderr)
        return SAIDA_NAO_CONGELADO
    oraculo = json.loads((RAIZ_REPO / do_oraculo["arquivo"]).read_text(encoding="utf-8"))
    if oraculo["versao_api"] != args.tag:
        print(f"o oráculo é da tag {oraculo['versao_api']}, não de {args.tag}", file=sys.stderr)
        return 2
    if not (args.api / ".git").exists():
        print(f"a API cobaia não foi encontrada em {args.api.resolve()}; o caminho de --api é relativo à "
              f"pasta de trabalho ({Path.cwd()})", file=sys.stderr)
        return 2
    commits = commits_atuais()
    if any(c.endswith(prompts.SUFIXO_ALTERADO) for c in commits):  # D105: o log diria com que código rodou
        print(f"há mudança não gravada nos prompts ou no código ({commits[0]}, {commits[1]}); grave antes de "
              f"gastar", file=sys.stderr)
        return SAIDA_NAO_CONGELADO
    try:  # antes de ler a chave: uma pasta recusada não gasta nada (T53)
        anteriores = carregar_anteriores(args.saida, args.retomar, cabecalho(args.tag, do_oraculo, commits,
                                                                             LIMITE_CASO_S))
    except RetomadaInvalida as exc:
        print(f"a rodada não roda: {exc}", file=sys.stderr)
        return 2
    casos = carregar_casos(oraculo, ids=set(args.casos) if args.casos else None)
    tratamentos = tuple(t for t in ORDEM_DOS_TRATAMENTOS if t in args.tratamentos)
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    if not com_agentes:  # só a baseline: sem LLM, sem chave, sem orçamento e sem confirmação (D75)
        print(f"casos {', '.join(c.id_caso for c in casos)} | só a baseline, {REPETICOES_BASELINE} repetição "
              f"(D92) | sem LLM, gasto US$ 0")
        return executar_rodada(casos, por_id, args.api, args.tag, args.saida, args.repeticoes, None, commits,
                               rodar, oraculo=do_oraculo, anteriores=anteriores, tratamentos=tratamentos)
    ja_gasto = gasto_do_log(args.saida / ARQUIVO_CHAMADAS)[0]
    if sdk is None:
        sdk = cliente_claude.criar_sdk(cliente_claude.ler_chave(args.env or RAIZ_REPO / ".env"))
    log = LogDeChamadas(args.saida / ARQUIVO_CHAMADAS)
    orcamento = Orcamento(args.orcamento_usd, log.caminho)
    print(f"casos {', '.join(c.id_caso for c in casos)} | {' e '.join(tratamentos)} | {args.repeticoes} "
          f"repetição(ões) nos agentes | modelo "
          f"{cliente_claude.MODELO} | trava de US$ {args.orcamento_usd:.2f}"
          + (f" (já gastos US$ {ja_gasto:.6f} nesta pasta)" if args.retomar else ""))
    if not args.sim:
        print(f"ATENÇÃO: vai chamar a API PAGA (trava de US$ {args.orcamento_usd:.2f} para a rodada inteira"
              + (f", já gastos US$ {ja_gasto:.6f} nesta pasta" if args.retomar else "") + ").")
        if input("Digite SIM para continuar: ").strip() != "SIM":
            print("cancelado, nada foi gasto")
            return 1

    def criar_fabrica(id_caso: str, repeticao: int):  # uma FabricaClaude por execução (T23i)
        return com_trava(cliente_claude.FabricaClaude(sdk, log, id_caso, repeticao, commits[0]), orcamento)

    codigo = executar_rodada(casos, por_id, args.api, args.tag, args.saida, args.repeticoes, criar_fabrica,
                             commits, rodar, oraculo=do_oraculo, anteriores=anteriores, tratamentos=tratamentos)
    gasto, tokens = gasto_do_log(log.caminho)
    print(f"gasto da rodada: US$ {gasto:.6f} | tokens: {tokens}"
          + (" (com as sessões anteriores desta pasta)" if args.retomar else ""))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
