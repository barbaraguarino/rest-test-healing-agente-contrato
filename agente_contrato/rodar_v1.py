"""Runner da v1 do Agente 1 (Classifier + Repair, pipeline fixo; D58, D62, D103, D105).

Uso, na raiz do repositório (IntelliJ: módulo `agente_contrato.rodar_v1`, diretório de trabalho = raiz):

    python -m agente_contrato.rodar_v1 --etapa 1 --api ../rest-test-healing-sut --saida resultados/t09-etapa1
    python -m agente_contrato.rodar_v1 --etapa 2 --api ... --saida ... --orcamento-usd 0.10
    python -m agente_contrato.rodar_v1 --etapa 3 --api ... --saida ... --orcamento-usd 0.10
    python -m agente_contrato.rodar_v1 --etapa 4 --api ... --saida resultados/t10-piloto --orcamento-usd 0.30
    python -m agente_contrato.rodar_v1 --etapa 4 ... --retomar   # continua a rodada interrompida

Limites de tempo da D111: `--limite-teste-s` (120), `--limite-caso-s` (180) e `--limite-llm-s` (120).

As etapas 1 a 3 são as da escada da D105. A etapa 4 é o piloto da T10: os 12 casos, 3 repetições,
só com os prompts do commit congelado e uma execução de aquecimento do Maven antes (D111f).
Quem chama o LLM é o `Chamador`; o LLM nunca roda o Maven nem grava arquivo.

Separação exigida pelo CLAUDE.md: `executar_caso` recebe só id, patch e nome do teste afetado e
nunca vê o oráculo; o rótulo, a categoria e a correção esperada entram em `registrar`, depois.
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from . import (baseline, chamada_llm, contrato, evidencia, execucao, guarda, leitura_falha, prompts,
               registro_llm, resultados, rodar_baseline, saida)
from .chamada_llm import ErroDeRede, ErroFatal
from .rodar_baseline import Entrada, Execucao
from .registro_llm import LogDeChamadas, Orcamento

TAG_PADRAO = rodar_baseline.TAG_PADRAO
TRATAMENTO, VERSAO = "agentes", "v1"
MAX_ERROS_LLM_SEGUIDOS = 3  # D104: valor inicial, a revisar depois da T09
CASO_DA_ETAPA_2 = "A1-001"
CASOS_DA_ETAPA_3 = ("A1-001", "A1-004", "A1-010", "A1-003")  # D105
REPETICOES_DA_ETAPA_4 = 3  # Planejamento: 3 repetições por caso nos agentes
COMMIT_DOS_PROMPTS_DA_T10 = "51894a8b561c7581216994e4001fd92b249061ac"  # D105: prompts congelados da v1

# Códigos de saída: quem chama (IntelliJ) vê por que a rodada parou.
SAIDA_OK, SAIDA_ERRO_FATAL, SAIDA_ORCAMENTO, SAIDA_ERROS_SEGUIDOS, SAIDA_PROMPT_GRANDE = 0, 3, 4, 5, 6
SAIDA_NAO_CONGELADO = 7


@dataclass
class Conta:
    """Tokens e dólares de um (caso, repetição), somando as reexecuções, que também são pagas."""
    tokens: int = 0
    custo_usd: float = 0.0
    chamadas: int = 0


class Chamador:
    """Cliente, log e orçamento juntos: cada chamada é conferida antes, registrada e somada."""

    def __init__(self, cliente, log: LogDeChamadas, orcamento: Orcamento, textos: dict[str, str],
                 commit_do_prompt: str):
        self.cliente, self.log, self.orcamento = cliente, log, orcamento
        self.textos, self.commit = textos, commit_do_prompt

    def _linha(self, id_caso, repeticao, etapa, **campos):
        base = dict(id_caso=id_caso, repeticao=repeticao, etapa=etapa, modelo_retornado=None, stop_reason=None,
                    input_tokens=None, output_tokens=None, thinking_tokens=None, custo_usd=None,
                    request_id=None, latencia_s=None, commit_do_prompt=self.commit, resposta_bruta=None,
                    erro=None)
        self.log.registrar(**{**base, **campos})

    def chamar(self, id_caso: str, repeticao: int, etapa: str, usuario: str, schema: dict, conta: Conta,
               limite: execucao.LimiteDoCaso | None = None):
        """`limite`: o relógio do caso, que confere antes e para de contar durante a espera (D111b)."""
        self.orcamento.verificar()  # antes de gastar, nunca depois
        if limite is not None:
            limite.verificar()
        try:
            with limite.fora_da_conta() if limite is not None else nullcontext():
                r = self.cliente.chamar(self.textos[etapa], usuario, schema)
        except (ErroDeRede, ErroFatal) as e:
            self._linha(id_caso, repeticao, etapa, custo_usd=0.0, latencia_s=round(e.latencia_s, 3),
                        erro=f"{type(e).__name__}: {e.motivo}")
            raise
        dados = dict(modelo_retornado=r.modelo, stop_reason=r.stop_reason, input_tokens=r.uso.input_tokens,
                     output_tokens=r.uso.output_tokens, thinking_tokens=r.uso.thinking_tokens,
                     request_id=r.request_id, latencia_s=round(r.latencia_s, 3), resposta_bruta=r.texto)
        conta.tokens += r.uso.total
        conta.chamadas += 1
        try:
            custo = registro_llm.custo_usd(r.uso)
        except registro_llm.PromptAcimaDoLimite as e:  # já foi pago, mas a tabela de preços não vale
            self._linha(id_caso, repeticao, etapa, erro=f"PromptAcimaDoLimite: {e}", **dados)
            raise
        self.orcamento.somar(r.uso, custo)
        conta.custo_usd += custo
        self._linha(id_caso, repeticao, etapa, custo_usd=custo, **dados)
        return r


@dataclass
class CasoPreparado:
    arquivo: Path
    relativo: str
    original: str
    mudancas: list
    rotas: dict
    evidencia: str
    maven_s: float
    teste_s: float
    tentativas_maven_inicial: int = 1


@contextmanager
def preparar(entrada: Entrada, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste,
             limite_teste_s: float = execucao.LIMITE_TESTE_S):
    """Cópia limpa da tag, patch do caso, teste afetado falhando e evidência montada.

    A evidência é calculada depois do patch: o LLM vê o código novo e o contrato novo.
    """
    copia = execucao.preparar_copia(api, tag, trabalho)
    try:
        antigo = contrato.carregar(copia / "docs" / "openapi.json")
        execucao.aplicar_patch(copia, entrada.patch)
        novo = contrato.carregar(copia / "docs" / "openapi.json")
        arquivo = execucao.arquivo_de_teste(copia, entrada.classe)
        original = arquivo.read_text(encoding="utf-8")

        inicial, tentativas = execucao.rodar_teste_inicial(rodar, copia, entrada.classe, entrada.metodo,
                                                           limite_teste_s)
        if inicial.passou:
            raise execucao.ErroDeExecucao(f"{entrada.id_caso}: o teste afetado passa sem reparo",
                                          causa="teste_passa_sem_reparo")
        mudancas = contrato.diferenca(antigo, novo)
        texto = evidencia.montar(mudancas, leitura_falha.ler_falha(copia), entrada.classe, entrada.metodo,
                                 original, evidencia.arquivos_do_modulo(copia, arquivo))
        yield CasoPreparado(arquivo, str(arquivo.relative_to(copia)), original, mudancas,
                            contrato.rotas_do_contrato(novo), texto, inicial.duracao_maven_s,
                            inicial.duracao_teste_s, tentativas), copia
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def _pipeline(p: CasoPreparado, entrada: Entrada, chamador: Chamador, repeticao: int, conta: Conta,
              e: Execucao, extras: dict, limite: execucao.LimiteDoCaso) -> str | None:
    """Classifier, depois Repair. Devolve o arquivo reparado aceito pelo guarda, ou None.

    Cada rejeição preenche `e.erro` (D74/D102) e encerra o caso; nada é repetido (D102). O estouro
    do caso antes de uma chamada também (`timeout`, D111d).
    """
    try:
        r1 = chamador.chamar(entrada.id_caso, repeticao, "classifier", p.evidencia, saida.SCHEMA_CLASSIFIER, conta,
                             limite)
        classificacao = saida.ler_classificacao(r1.stop_reason, r1.texto)
        extras.update(rotulo_classifier=classificacao.rotulo, justificativa=classificacao.justificativa)
        if classificacao.rotulo == saida.PROBLEMA_REAL:
            return None  # o código decide pular o Repair (D62); não é erro
        r2 = chamador.chamar(entrada.id_caso, repeticao, "repair", p.evidencia, saida.SCHEMA_REPAIR, conta, limite)
        reparado = saida.encaixar(p.original, entrada.metodo, saida.ler_reparo(r2.stop_reason, r2.texto))
    except saida.SaidaRejeitada as rejeicao:
        e.erro, extras["motivo_erro"] = rejeicao.codigo, rejeicao.motivo
        return None
    except execucao.ErroDeExecucao as estouro:
        if estouro.codigo != "timeout":
            raise
        e.erro, e.estouro, extras["motivo_erro"] = "timeout", estouro.causa, str(estouro)
        return None
    veredito = guarda.avaliar(p.original, reparado, entrada.metodo, p.mudancas, p.rotas)
    e.guarda_motivos = veredito.motivos
    if not veredito.aceito:
        e.erro = "guarda"
        return None
    return reparado


def executar_caso(entrada: Entrada, api: Path, tag: str, trabalho: Path, chamador: Chamador, repeticao: int,
                  conta: Conta, rodar=execucao.rodar_teste,
                  limites: execucao.Limites = execucao.Limites()) -> tuple[Execucao, dict]:
    with preparar(entrada, api, tag, trabalho, rodar, limites.teste_s) as (p, copia):
        limite = limites.caso()  # D111b: a partir da falha recebida
        e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False, None,
                     0.0, original=p.original, arquivo_relativo=p.relativo, mudancas=p.mudancas, rotas=p.rotas,
                     maven_s=[p.maven_s], teste_s=[p.teste_s], tentativas_maven_inicial=p.tentativas_maven_inicial)
        extras = {"rotulo_classifier": None, "justificativa": None, "motivo_erro": None}
        inicio = time.monotonic()
        reparado = _pipeline(p, entrada, chamador, repeticao, conta, e, extras, limite)
        e.tempo_s = time.monotonic() - inicio  # da falha ao artefato final, com as chamadas ao LLM

        if reparado is not None:
            p.arquivo.write_text(reparado, encoding="utf-8")
            e.decisao, e.reparado = baseline.REPARAR, reparado
            rodar_baseline.rodar_final(e, rodar, copia, entrada, limite, limites)
        e.duracao_caso_s, e.espera_llm_s = limite.decorrido(), limite.espera_llm_s
        return e, extras


def _com_reexecucao(entrada, api, tag, trabalho: Path, chamador, repeticao, conta, rodar, limites):
    """D104: erro de rede ou de infraestrutura do LLM reexecuta o caso uma vez; falhando de novo, `erro_llm`.

    Cada tentativa tem o seu relógio do caso. O Maven inicial já tem a sua reexecução (D111e).
    """
    for tentativa in (1, 2):
        try:
            e, extras = executar_caso(entrada, api, tag, trabalho / f"{entrada.id_caso}-r{repeticao}-t{tentativa}",
                                      chamador, repeticao, conta, rodar, limites)
            return e, extras, tentativa
        except ErroDeRede as exc:
            print(f"{entrada.id_caso} r{repeticao}: erro de rede na tentativa {tentativa}: {exc.motivo}", flush=True)
            motivo = exc.motivo
        except execucao.ErroDeExecucao as exc:
            print(f"{entrada.id_caso} r{repeticao}: ERRO {exc.codigo} ({exc.causa}): {exc}", flush=True)
            e = rodar_baseline.com_erro_de_execucao(entrada, exc)
            return e, {"rotulo_classifier": None, "justificativa": None, "motivo_erro": str(exc)}, tentativa
    e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False, "erro_llm", 0.0,
                 causa="erro_llm")
    return e, {"rotulo_classifier": None, "justificativa": None, "motivo_erro": motivo}, 2


def commit_do_codigo() -> str:
    """Hash do último commit que mexeu em `agente_contrato/`, com `+alterado` se há mudança pendente.

    Vai para o resumo de cada caso, para o resultado dizer com que código foi gravado sem depender do README.
    """
    return prompts.commit_dos_prompts(Path(__file__).resolve().parent)


# ---------------------------------------------------------------- etapa 4: congelamento, aquecimento, retomada

def conferir_congelamento(commit_prompts: str, commit_codigo: str) -> str | None:
    """Motivo para a etapa 4 não rodar, ou None. Os resultados da T10 só valem com os prompts
    congelados (D105); código com mudança pendente também não, porque o commit gravado não diria o que rodou."""
    if commit_prompts != COMMIT_DOS_PROMPTS_DA_T10:
        return (f"os prompts estão em {commit_prompts}, e não no commit congelado {COMMIT_DOS_PROMPTS_DA_T10[:7]} "
                f"(D105)")
    if commit_codigo.endswith(prompts.SUFIXO_ALTERADO):
        return f"há mudança não commitada em agente_contrato/ ({commit_codigo})"
    return None


def aquecer(entrada: Entrada, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste,
            limite_teste_s: float = execucao.LIMITE_TESTE_S) -> dict:
    """D111f: uma execução do Maven na tag limpa, sem patch, antes do primeiro caso medido.

    Roda o teste afetado do primeiro caso pendente (sem o patch, ele passa). Fica só no log, fora das
    métricas; um erro aqui não para a rodada, porque o Maven inicial de cada caso tem as próprias travas.
    """
    dados = {"teste": f"{entrada.classe}.{entrada.metodo}", "passou": None, "duracao_maven_s": None, "erro": None}
    try:
        copia = execucao.preparar_copia(api, tag, trabalho)
        r = rodar(copia, entrada.classe, entrada.metodo, timeout_s=limite_teste_s)
        dados.update(passou=r.passou, duracao_maven_s=round(r.duracao_maven_s, 2))
    except execucao.ErroDeExecucao as exc:
        dados["erro"] = f"{exc.codigo} ({exc.causa}): {exc}"
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    return dados


class RetomadaInvalida(Exception):
    """A pasta de saída não pode receber esta rodada (D105: uma rodada, um prompt, um código)."""


@dataclass
class Anteriores:
    """O que uma rodada interrompida já gravou na pasta. Só vale a execução que está nos dois
    arquivos: a queda entre gravar o resultado e gravar o log faz a execução rodar de novo."""
    registros: list = field(default_factory=list)
    resumo: list = field(default_factory=list)
    sessoes: list = field(default_factory=list)
    chamadas_sem_registro: list = field(default_factory=list)  # pagas, de execuções que não chegaram ao fim

    def feitos(self) -> set:
        return {(x["id_caso"], x["repeticao"]) for x in self.resumo}


def _ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else None


def carregar_anteriores(pasta: Path, tag: str, retomar: bool, commit_prompts: str, commit_codigo: str,
                        limites: execucao.Limites) -> Anteriores:
    """Sem `retomar`, exige pasta sem resultados nem chamadas. Com `retomar`, devolve o que já foi
    gravado, recusando misturar prompt, código, limites ou tag diferentes na mesma rodada."""
    arquivos = [pasta / n for n in ("resultados-agente1.json", "log-v1.json", "chamadas.jsonl")]
    if not retomar:
        if any(a.exists() for a in arquivos):
            raise RetomadaInvalida(f"{pasta} já tem uma rodada; use --retomar para continuar ou outra --saida")
        return Anteriores()
    dados, log = _ler_json(arquivos[0]), _ler_json(arquivos[1])
    if dados is not None and dados["versao_api"] != tag:
        raise RetomadaInvalida(f"a rodada gravada é da tag {dados['versao_api']}, não de {tag}")
    if log is None:
        log = {"limites": limites.para_o_log(), "execucoes": [], "sessoes": []}
    if log["limites"] != limites.para_o_log():
        raise RetomadaInvalida(f"a rodada gravada usou os limites {log['limites']}, não {limites.para_o_log()}")
    for x in log["execucoes"]:
        if (x["commit_do_prompt"], x["commit_do_codigo"]) != (commit_prompts, commit_codigo):
            raise RetomadaInvalida(f"{x['id_caso']} r{x['repeticao']} foi gravado com prompts {x['commit_do_prompt']} "
                                   f"e código {x['commit_do_codigo']}; agora são {commit_prompts} e {commit_codigo}")
    registros = (dados or {"execucoes": []})["execucoes"]
    no_resultado = {(r["id_caso"], r["repeticao"]) for r in registros}
    resumo = [x for x in log["execucoes"] if (x["id_caso"], x["repeticao"]) in no_resultado]
    a = Anteriores(resumo=resumo, sessoes=log.get("sessoes", []))
    feitos = a.feitos()
    a.registros = [r for r in registros if (r["id_caso"], r["repeticao"]) in feitos]
    if arquivos[2].exists():
        contagem = {}
        for linha in arquivos[2].read_text(encoding="utf-8").splitlines():
            if linha.strip():
                c = json.loads(linha)
                if (c["id_caso"], c["repeticao"]) not in feitos:
                    contagem[(c["id_caso"], c["repeticao"])] = contagem.get((c["id_caso"], c["repeticao"]), 0) + 1
        a.chamadas_sem_registro = [{"id_caso": i, "repeticao": r, "chamadas": n} for (i, r), n in contagem.items()]
    return a


def _gravar_log(pasta: Path, limites: execucao.Limites, resumo: list, sessoes: list) -> None:
    fora = rodar_baseline.exclusoes(resumo)
    (pasta / "log-v1.json").write_text(
        json.dumps({"limites": limites.para_o_log(), **fora, "sessoes": sessoes, "execucoes": resumo},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- rodada

def executar_rodada(entradas: list[Entrada], oraculos: dict, api: Path, tag: str, raiz_repo: Path, pasta: Path,
                    repeticoes: int, chamador: Chamador, rodar=execucao.rodar_teste,
                    commit_codigo: str | None = None,
                    limites: execucao.Limites = execucao.Limites(llm_s=chamada_llm.TIMEOUT_S),
                    anteriores: Anteriores | None = None, aquecer_antes: bool = False) -> int:
    """Roda os casos e grava, a cada caso, o arquivo de resultados (D74) e o resumo. Devolve o código de saída.

    `commit_codigo` nulo só nos testes e no ensaio com cliente falso; `main` passa o de `commit_do_codigo()`.
    `anteriores`: execuções já gravadas por esta rodada, que são puladas (retomada da etapa 4). Cada vez que
    o comando roda vira uma entrada de `sessoes` no log, com o aquecimento e as chamadas pagas sem registro.
    """
    anteriores = anteriores or Anteriores()
    feitos = anteriores.feitos()
    registros, resumo, sessoes = list(anteriores.registros), list(anteriores.resumo), list(anteriores.sessoes)
    seguidos = 0
    pendentes = [(en, rep) for en in entradas for rep in range(1, repeticoes + 1) if (en.id_caso, rep) not in feitos]
    pasta.mkdir(parents=True, exist_ok=True)
    print(f"limites: teste {limites.teste_s:g} s, caso {limites.caso_s:g} s, chamada ao LLM {limites.llm_s:g} s "
          f"(D111)", flush=True)
    if feitos:
        print(f"retomada: {len(feitos)} execuções já gravadas, {len(pendentes)} a rodar; chamadas pagas sem "
              f"registro: {sum(c['chamadas'] for c in anteriores.chamadas_sem_registro)}", flush=True)
    if not pendentes:
        print("nada a rodar: todas as execuções já estão gravadas", flush=True)
        return SAIDA_OK
    with tempfile.TemporaryDirectory(prefix="v1-") as trabalho:
        sessao = {"inicio_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "execucoes_ja_gravadas": len(feitos),
                  "chamadas_sem_registro": anteriores.chamadas_sem_registro, "aquecimento": None}
        sessoes.append(sessao)
        if aquecer_antes:
            sessao["aquecimento"] = aquecer(pendentes[0][0], api, tag, Path(trabalho) / "aquecimento", rodar,
                                            limites.teste_s)
            a = sessao["aquecimento"]
            print(f"aquecimento do Maven (D111f, fora das métricas): {a['teste']} passou={a['passou']} "
                  f"maven={a['duracao_maven_s']} s erro={a['erro']}", flush=True)
        _gravar_log(pasta, limites, resumo, sessoes)
        for entrada, repeticao in pendentes:
            conta = Conta()
            try:
                e, extras, tentativas = _com_reexecucao(entrada, api, tag, Path(trabalho), chamador,
                                                        repeticao, conta, rodar, limites)
            except ErroFatal as exc:
                print(f"PARADA: erro que repetir não resolve: {exc.motivo}", file=sys.stderr)
                return SAIDA_ERRO_FATAL
            except registro_llm.OrcamentoEsgotado as exc:
                print(f"PARADA: {exc}", file=sys.stderr)
                return SAIDA_ORCAMENTO
            except registro_llm.PromptAcimaDoLimite as exc:
                print(f"PARADA: {exc}", file=sys.stderr)
                return SAIDA_PROMPT_GRANDE
            e.tokens, e.custo_usd = conta.tokens, round(conta.custo_usd, 8)
            registro, do_registro = rodar_baseline.registrar(e, oraculos[entrada.id_caso], repeticao, raiz_repo,
                                                             TRATAMENTO, VERSAO)
            registros.append(registro)
            resumo.append({"id_caso": e.id_caso, "repeticao": repeticao, "erro": e.erro, "causa": e.causa,
                           "tentativas": tentativas, **extras, "chamadas": conta.chamadas, "tokens": conta.tokens,
                           "custo_usd": e.custo_usd, "guarda": list(e.guarda_motivos), **e.para_o_log(),
                           "commit_do_prompt": chamador.commit, "commit_do_codigo": commit_codigo,
                           **do_registro})
            resultados.gravar(pasta / "resultados-agente1.json", tag, registros)
            _gravar_log(pasta, limites, resumo, sessoes)
            print(f"{e.id_caso} r{repeticao}: decisao={registro['decisao']} compilou={registro['compilou']} "
                  f"passou={registro['passou']} erro={registro['erro']} estouro={e.estouro} tokens={conta.tokens} "
                  f"custo=US$ {e.custo_usd:.6f} (acumulado US$ {chamador.orcamento.gasto_usd:.6f})", flush=True)
            seguidos = seguidos + 1 if e.erro == "erro_llm" else 0
            if seguidos >= MAX_ERROS_LLM_SEGUIDOS:
                print(f"PARADA: {seguidos} erro_llm seguidos", file=sys.stderr)
                rodar_baseline.imprimir_exclusoes(rodar_baseline.exclusoes(resumo))
                return SAIDA_ERROS_SEGUIDOS
    rodar_baseline.imprimir_exclusoes(rodar_baseline.exclusoes(resumo))
    return SAIDA_OK


# ---------------------------------------------------------------- etapas 1 e 2 da D105

def etapa_1(entradas: list[Entrada], api: Path, tag: str, cliente, textos: dict[str, str], commit: str,
            pasta: Path, rodar=execucao.rodar_teste) -> int:
    """Conta os tokens de entrada dos prompts reais (gratuito) e grava `contagem-de-tokens.json`.

    Não chama o modelo. O arquivo é regravado a cada caso, para uma queda do Maven não perder o que já foi contado.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    contagens = []
    with tempfile.TemporaryDirectory(prefix="v1-") as trabalho:
        for entrada in entradas:
            with preparar(entrada, api, tag, Path(trabalho) / entrada.id_caso, rodar) as (p, _):
                for etapa in ("classifier", "repair"):
                    n = cliente.contar_tokens(textos[etapa], p.evidencia)
                    custo = registro_llm.custo_usd(registro_llm.Uso(n, 0, None))
                    caracteres = len(textos[etapa]) + len(p.evidencia)
                    contagens.append({"id_caso": entrada.id_caso, "prompt": etapa, "tokens_de_entrada": n,
                                      "caracteres": caracteres, "custo_so_da_entrada_usd": custo})
                    print(f"{entrada.id_caso} {etapa}: {n} tokens de entrada (estimativa da API; "
                          f"{caracteres} caracteres; só a entrada custaria US$ {custo:.6f})", flush=True)
            (pasta / "contagem-de-tokens.json").write_text(json.dumps(
                {"data_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "modelo": chamada_llm.MODELO,
                 "commit_dos_prompts": commit, "contagens": contagens}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
    return SAIDA_OK


def _nota_do_thinking(uso: registro_llm.Uso) -> str:
    """Só afirma que o thinking está dentro de `output_tokens` quando houve thinking para medir:
    com 0 a comparação é trivial e não prova nada (a primeira etapa 2 real teve 0 de 164 tokens)."""
    t = uso.thinking_tokens
    if t is None:
        return "  (a API não informou)"
    if t == 0:
        return "  (o modelo não pensou nesta chamada: isto NÃO confirma se o thinking entra em output_tokens)"
    if t <= uso.output_tokens:
        return "  (<= output_tokens: o thinking está dentro da saída)"
    return "  (ATENÇÃO: maior que output_tokens; o thinking pode ser cobrado à parte)"


def etapa_2(entrada: Entrada, api: Path, tag: str, chamador: Chamador, rodar=execucao.rodar_teste) -> int:
    """Uma chamada real do Classifier e tudo o que a D105 manda verificar nela."""
    conta = Conta()
    with tempfile.TemporaryDirectory(prefix="v1-") as trabalho:
        with preparar(entrada, api, tag, Path(trabalho) / entrada.id_caso, rodar) as (p, _):
            try:
                r = chamador.chamar(entrada.id_caso, 1, "classifier", p.evidencia, saida.SCHEMA_CLASSIFIER, conta)
            except ErroFatal as exc:
                print(f"PARADA: {exc.motivo}", file=sys.stderr)
                return SAIDA_ERRO_FATAL
            except ErroDeRede as exc:
                print(f"PARADA: erro de rede: {exc.motivo}", file=sys.stderr)
                return SAIDA_ERRO_FATAL
    print(f"modelo retornado : {r.modelo}")
    print(f"stop_reason      : {r.stop_reason}")
    print(f"request_id       : {r.request_id}")
    print(f"latência         : {r.latencia_s:.2f} s")
    print(f"input_tokens     : {r.uso.input_tokens}")
    print(f"output_tokens    : {r.uso.output_tokens}")
    print(f"thinking_tokens  : {r.uso.thinking_tokens}" + _nota_do_thinking(r.uso))
    print(f"custo            : US$ {conta.custo_usd:.6f}")
    print(f"resposta bruta   : {r.texto}")
    try:
        c = saida.ler_classificacao(r.stop_reason, r.texto)
        print(f"validação        : OK, rótulo {c.rotulo!r}")
    except saida.SaidaRejeitada as rej:
        print(f"validação        : REJEITADA ({rej.codigo}): {rej.motivo}")
    return SAIDA_OK


# ---------------------------------------------------------------- linha de comando

def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--etapa", type=int, required=True, choices=(1, 2, 3, 4),
                    help="1 a 3: escada da D105; 4: piloto da T10 (12 casos, 3 repetições)")
    ap.add_argument("--api", required=True, type=Path, help="clone da API cobaia (rest-test-healing-sut)")
    ap.add_argument("--saida", required=True, type=Path, help="pasta de saída")
    ap.add_argument("--tag", default=TAG_PADRAO)
    ap.add_argument("--orcamento-usd", type=float,
                    help="obrigatório nas etapas 2 a 4; a rodada para ao chegar nele (na etapa 4, somando as retomadas)")
    ap.add_argument("--retomar", action="store_true",
                    help="só na etapa 4: continua a rodada interrompida na mesma --saida, sem refazer o que já foi gravado")
    ap.add_argument("--env", type=Path, help="arquivo .env com a chave (padrão: .env na raiz do repositório)")
    ap.add_argument("--sim", action="store_true", help="não pedir a confirmação antes de gastar")
    rodar_baseline.adicionar_limites(ap)
    ap.add_argument("--limite-llm-s", type=float, default=chamada_llm.TIMEOUT_S,
                    help="timeout de uma chamada ao LLM, em segundos (D104, D111c)")
    args = ap.parse_args(argv)
    if args.etapa in (2, 3, 4) and not args.orcamento_usd:
        ap.error("as etapas 2 a 4 chamam a API paga: informe --orcamento-usd (ex.: 0.10)")
    if args.retomar and args.etapa != 4:
        ap.error("--retomar só vale na etapa 4")
    return args


def main(argv: list[str] | None = None, criar_cliente=None, rodar=execucao.rodar_teste) -> int:
    args = _argumentos(argv)
    raiz_repo = Path(__file__).resolve().parent.parent
    oraculo = json.loads((raiz_repo / "casos" / "oraculo-agente1.json").read_text(encoding="utf-8"))
    if oraculo["versao_api"] != args.tag:
        print(f"o oráculo é da tag {oraculo['versao_api']}, não de {args.tag}", file=sys.stderr)
        return 2
    if not (args.api / ".git").exists():
        print(f"A API cobaia não foi encontrada em {args.api.resolve()}.\n"
              f"O caminho de --api é relativo ao diretório de trabalho ({Path.cwd()}); confira o nome da pasta.",
              file=sys.stderr)
        return 2
    ids = {1: CASOS_DA_ETAPA_3, 2: (CASO_DA_ETAPA_2,), 3: CASOS_DA_ETAPA_3,
           4: tuple(sorted(c["id_caso"] for c in oraculo["casos"]))}[args.etapa]
    entradas = rodar_baseline._carregar_entradas(raiz_repo, oraculo, set(ids))
    entradas.sort(key=lambda en: ids.index(en.id_caso))
    commit, codigo_do_codigo = prompts.commit_dos_prompts(), commit_do_codigo()
    limites = execucao.Limites(args.limite_teste_s, args.limite_caso_s, args.limite_llm_s)

    anteriores = None
    if args.etapa == 4:  # tudo conferido antes de ler a chave ou gastar
        motivo = conferir_congelamento(commit, codigo_do_codigo)
        if motivo:
            print(f"a etapa 4 não roda: {motivo}", file=sys.stderr)
            return SAIDA_NAO_CONGELADO
        try:
            anteriores = carregar_anteriores(args.saida, args.tag, args.retomar, commit, codigo_do_codigo, limites)
        except RetomadaInvalida as exc:
            print(f"a etapa 4 não roda: {exc}", file=sys.stderr)
            return 2

    if criar_cliente is None:
        def criar_cliente():
            return chamada_llm.ClienteAnthropic(chamada_llm.ler_chave(args.env or raiz_repo / ".env"),
                                                timeout_s=args.limite_llm_s)
    cliente = criar_cliente()
    textos = {"classifier": prompts.carregar("classifier"), "repair": prompts.carregar("repair")}
    print(f"etapa {args.etapa} | casos {', '.join(ids)} | modelo {chamada_llm.MODELO} | prompts {commit} "
          f"| código {codigo_do_codigo}")

    if args.etapa == 1:
        return etapa_1(entradas, args.api, args.tag, cliente, textos, commit, args.saida, rodar)

    log_chamadas = args.saida / "chamadas.jsonl"
    ja_gasto, ja_tokens = registro_llm.gasto_do_log(log_chamadas) if args.retomar else (0.0, 0)
    if not args.sim:
        print(f"ATENÇÃO: vai chamar a API PAGA (trava de US$ {args.orcamento_usd:.2f}"
              + (f", já gastos US$ {ja_gasto:.6f} nesta pasta" if args.retomar else "") + ").")
        if input("Digite SIM para continuar: ").strip() != "SIM":
            print("cancelado, nada foi gasto")
            return 1
    chamador = Chamador(cliente, LogDeChamadas(log_chamadas), Orcamento(args.orcamento_usd, ja_gasto, ja_tokens),
                        textos, commit)
    if args.etapa == 2:
        return etapa_2(entradas[0], args.api, args.tag, chamador, rodar)
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    repeticoes = REPETICOES_DA_ETAPA_4 if args.etapa == 4 else 1
    codigo = executar_rodada(entradas, por_id, args.api, args.tag, raiz_repo, args.saida, repeticoes, chamador,
                             rodar, codigo_do_codigo, limites, anteriores, aquecer_antes=args.etapa == 4)
    print(f"gasto total: US$ {chamador.orcamento.gasto_usd:.6f} | tokens: {chamador.orcamento.tokens}"
          + (" (com as sessões anteriores desta pasta)" if args.retomar else ""))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
