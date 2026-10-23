"""Runner da v1 do Agente 1 (Classifier + Repair, pipeline fixo; D58, D62, D103, D105).

Uso, na raiz do repositório (IntelliJ: módulo `agente_contrato.rodar_v1`, diretório de trabalho = raiz):

    python -m agente_contrato.rodar_v1 --etapa 1 --api ../rest-test-healing-sut --saida resultados/t09-etapa1
    python -m agente_contrato.rodar_v1 --etapa 2 --api ... --saida ... --orcamento-usd 0.10
    python -m agente_contrato.rodar_v1 --etapa 3 --api ... --saida ... --orcamento-usd 0.10

As etapas são as da escada da D105. O piloto completo (12 casos, 3 repetições) é a T10 e não
roda aqui. Quem chama o LLM é o `Chamador`; o LLM nunca roda o Maven nem grava arquivo.

Separação exigida pelo CLAUDE.md: `executar_caso` recebe só id, patch e nome do teste afetado e
nunca vê o oráculo; o rótulo, a categoria e a correção esperada entram em `registrar`, depois.
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import dataclass
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

# Códigos de saída: quem chama (IntelliJ) vê por que a rodada parou.
SAIDA_OK, SAIDA_ERRO_FATAL, SAIDA_ORCAMENTO, SAIDA_ERROS_SEGUIDOS, SAIDA_PROMPT_GRANDE = 0, 3, 4, 5, 6


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

    def chamar(self, id_caso: str, repeticao: int, etapa: str, usuario: str, schema: dict, conta: Conta):
        self.orcamento.verificar()  # antes de gastar, nunca depois
        try:
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


@contextmanager
def preparar(entrada: Entrada, api: Path, tag: str, trabalho: Path, rodar=execucao.rodar_teste):
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

        inicial = rodar(copia, entrada.classe, entrada.metodo)
        if inicial.passou:
            raise execucao.ErroDeExecucao(f"{entrada.id_caso}: o teste afetado passa sem reparo")
        mudancas = contrato.diferenca(antigo, novo)
        texto = evidencia.montar(mudancas, leitura_falha.ler_falha(copia), entrada.classe, entrada.metodo,
                                 original, evidencia.arquivos_do_modulo(copia, arquivo))
        yield CasoPreparado(arquivo, str(arquivo.relative_to(copia)), original, mudancas,
                            contrato.rotas_do_contrato(novo), texto, inicial.duracao_maven_s,
                            inicial.duracao_teste_s), copia
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def _pipeline(p: CasoPreparado, entrada: Entrada, chamador: Chamador, repeticao: int, conta: Conta,
              e: Execucao, extras: dict) -> str | None:
    """Classifier, depois Repair. Devolve o arquivo reparado aceito pelo guarda, ou None.

    Cada rejeição preenche `e.erro` (D74/D102) e encerra o caso; nada é repetido (D102).
    """
    try:
        r1 = chamador.chamar(entrada.id_caso, repeticao, "classifier", p.evidencia, saida.SCHEMA_CLASSIFIER, conta)
        classificacao = saida.ler_classificacao(r1.stop_reason, r1.texto)
        extras.update(rotulo_classifier=classificacao.rotulo, justificativa=classificacao.justificativa)
        if classificacao.rotulo == saida.PROBLEMA_REAL:
            return None  # o código decide pular o Repair (D62); não é erro
        r2 = chamador.chamar(entrada.id_caso, repeticao, "repair", p.evidencia, saida.SCHEMA_REPAIR, conta)
        reparado = saida.encaixar(p.original, entrada.metodo, saida.ler_reparo(r2.stop_reason, r2.texto))
    except saida.SaidaRejeitada as rejeicao:
        e.erro, extras["motivo_erro"] = rejeicao.codigo, rejeicao.motivo
        return None
    veredito = guarda.avaliar(p.original, reparado, entrada.metodo, p.mudancas, p.rotas)
    e.guarda_motivos = veredito.motivos
    if not veredito.aceito:
        e.erro = "guarda"
        return None
    return reparado


def executar_caso(entrada: Entrada, api: Path, tag: str, trabalho: Path, chamador: Chamador, repeticao: int,
                  conta: Conta, rodar=execucao.rodar_teste) -> tuple[Execucao, dict]:
    with preparar(entrada, api, tag, trabalho, rodar) as (p, copia):
        e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False, None,
                     0.0, original=p.original, arquivo_relativo=p.relativo, mudancas=p.mudancas, rotas=p.rotas,
                     maven_s=[p.maven_s], teste_s=[p.teste_s])
        extras = {"rotulo_classifier": None, "justificativa": None, "motivo_erro": None}
        inicio = time.monotonic()
        reparado = _pipeline(p, entrada, chamador, repeticao, conta, e, extras)
        e.tempo_s = time.monotonic() - inicio  # da falha ao artefato final, com as chamadas ao LLM

        if reparado is not None:
            p.arquivo.write_text(reparado, encoding="utf-8")
            e.decisao, e.reparado = baseline.REPARAR, reparado
            final = rodar(copia, entrada.classe, entrada.metodo)
            e.compilou, e.passou = final.compilou, final.passou
            e.maven_s.append(final.duracao_maven_s)
            e.teste_s.append(final.duracao_teste_s)
        return e, extras


def _com_reexecucao(entrada, api, tag, trabalho: Path, chamador, repeticao, conta, rodar):
    """D104: erro de rede ou de infraestrutura do LLM reexecuta o caso uma vez; falhando de novo, `erro_llm`."""
    for tentativa in (1, 2):
        try:
            e, extras = executar_caso(entrada, api, tag, trabalho / f"{entrada.id_caso}-r{repeticao}-t{tentativa}",
                                      chamador, repeticao, conta, rodar)
            return e, extras, tentativa
        except ErroDeRede as exc:
            print(f"{entrada.id_caso} r{repeticao}: erro de rede na tentativa {tentativa}: {exc.motivo}", flush=True)
            motivo = exc.motivo
        except execucao.ErroDeExecucao as exc:
            print(f"{entrada.id_caso} r{repeticao}: ERRO {exc.codigo}: {exc}", flush=True)
            e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False,
                         exc.codigo, 0.0)
            return e, {"rotulo_classifier": None, "justificativa": None, "motivo_erro": str(exc)}, tentativa
    e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False, "erro_llm", 0.0)
    return e, {"rotulo_classifier": None, "justificativa": None, "motivo_erro": motivo}, 2


def executar_rodada(entradas: list[Entrada], oraculos: dict, api: Path, tag: str, raiz_repo: Path, pasta: Path,
                    repeticoes: int, chamador: Chamador, rodar=execucao.rodar_teste) -> int:
    """Roda os casos e grava, a cada caso, o arquivo de resultados (D74) e o resumo. Devolve o código de saída."""
    registros, resumo, seguidos = [], [], 0
    pasta.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v1-") as trabalho:
        for entrada in entradas:
            for repeticao in range(1, repeticoes + 1):
                conta = Conta()
                try:
                    e, extras, tentativas = _com_reexecucao(entrada, api, tag, Path(trabalho), chamador,
                                                            repeticao, conta, rodar)
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
                resumo.append({"id_caso": e.id_caso, "repeticao": repeticao, "tentativas": tentativas,
                               **extras, "chamadas": conta.chamadas, "tokens": conta.tokens,
                               "custo_usd": e.custo_usd, "guarda": list(e.guarda_motivos),
                               "duracao_maven_s": [round(x, 2) for x in e.maven_s],
                               "duracao_teste_s": [round(x, 2) for x in e.teste_s],
                               "commit_do_prompt": chamador.commit, **do_registro})
                resultados.gravar(pasta / "resultados-agente1.json", tag, registros)
                (pasta / "log-v1.json").write_text(
                    json.dumps({"execucoes": resumo}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"{e.id_caso} r{repeticao}: decisao={registro['decisao']} compilou={registro['compilou']} "
                      f"passou={registro['passou']} erro={registro['erro']} tokens={conta.tokens} "
                      f"custo=US$ {e.custo_usd:.6f} (acumulado US$ {chamador.orcamento.gasto_usd:.6f})", flush=True)
                seguidos = seguidos + 1 if e.erro == "erro_llm" else 0
                if seguidos >= MAX_ERROS_LLM_SEGUIDOS:
                    print(f"PARADA: {seguidos} erro_llm seguidos", file=sys.stderr)
                    return SAIDA_ERROS_SEGUIDOS
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
    com 0 a comparação é trivial e não prova nada (a etapa 2 de 22/10/2026 mostrou isso)."""
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
    ap.add_argument("--etapa", type=int, required=True, choices=(1, 2, 3), help="etapa da escada da D105")
    ap.add_argument("--api", required=True, type=Path, help="clone da API cobaia (rest-test-healing-sut)")
    ap.add_argument("--saida", required=True, type=Path, help="pasta de saída")
    ap.add_argument("--tag", default=TAG_PADRAO)
    ap.add_argument("--orcamento-usd", type=float, help="obrigatório nas etapas 2 e 3; a rodada para ao chegar nele")
    ap.add_argument("--env", type=Path, help="arquivo .env com a chave (padrão: .env na raiz do repositório)")
    ap.add_argument("--sim", action="store_true", help="não pedir a confirmação antes de gastar")
    args = ap.parse_args(argv)
    if args.etapa in (2, 3) and not args.orcamento_usd:
        ap.error("as etapas 2 e 3 chamam a API paga: informe --orcamento-usd (ex.: 0.10)")
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
    ids = {1: CASOS_DA_ETAPA_3, 2: (CASO_DA_ETAPA_2,), 3: CASOS_DA_ETAPA_3}[args.etapa]
    entradas = rodar_baseline._carregar_entradas(raiz_repo, oraculo, set(ids))
    entradas.sort(key=lambda en: ids.index(en.id_caso))

    if criar_cliente is None:
        def criar_cliente():
            return chamada_llm.ClienteAnthropic(chamada_llm.ler_chave(args.env or raiz_repo / ".env"))
    cliente = criar_cliente()
    textos = {"classifier": prompts.carregar("classifier"), "repair": prompts.carregar("repair")}
    commit = prompts.commit_dos_prompts()
    print(f"etapa {args.etapa} | casos {', '.join(ids)} | modelo {chamada_llm.MODELO} | prompts {commit}")

    if args.etapa == 1:
        return etapa_1(entradas, args.api, args.tag, cliente, textos, commit, args.saida, rodar)

    if not args.sim:
        print(f"ATENÇÃO: vai chamar a API PAGA (trava de US$ {args.orcamento_usd:.2f}).")
        if input("Digite SIM para continuar: ").strip() != "SIM":
            print("cancelado, nada foi gasto")
            return 1
    chamador = Chamador(cliente, LogDeChamadas(args.saida / "chamadas.jsonl"), Orcamento(args.orcamento_usd),
                        textos, commit)
    if args.etapa == 2:
        return etapa_2(entradas[0], args.api, args.tag, chamador, rodar)
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    codigo = executar_rodada(entradas, por_id, args.api, args.tag, raiz_repo, args.saida, 1, chamador, rodar)
    print(f"gasto total: US$ {chamador.orcamento.gasto_usd:.6f} | tokens: {chamador.orcamento.tokens}")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
