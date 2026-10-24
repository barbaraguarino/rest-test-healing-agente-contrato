"""Runner da baseline determinística do Agente 1: roda os casos e grava os resultados (D74).

Uso (na raiz do repositório):
    python3 -m agente_contrato.rodar_baseline --api CAMINHO_DA_API_COBAIA --saida PASTA [--repeticoes 3]
        [--limite-teste-s 120] [--limite-caso-s 180]

Separação exigida pelo CLAUDE.md: `executar_caso` recebe só id, patch e nome do
teste afetado e nunca vê o oráculo; o rótulo, a categoria e a correção esperada
entram em `registrar`, depois da execução.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import baseline, comparador, contrato, execucao, guarda, resultados

TAG_PADRAO = "linha-de-base-2"
REPETICOES_PADRAO = 3  # D92: no piloto a baseline roda 3 vezes só para confirmar o determinismo


@dataclass(frozen=True)
class Entrada:
    id_caso: str
    patch: Path
    classe: str
    metodo: str


@dataclass
class Execucao:
    id_caso: str
    classe: str
    metodo: str
    decisao: str
    compilou: bool | None
    passou: bool
    erro: str | None
    tempo_s: float
    original: str = ""
    reparado: str | None = None
    arquivo_relativo: str = ""
    mudancas: list = field(default_factory=list)
    rotas: dict = field(default_factory=dict)
    aplicadas: int = 0
    ignoradas: list = field(default_factory=list)
    guarda_motivos: tuple = ()
    maven_s: list = field(default_factory=list)
    teste_s: list = field(default_factory=list)
    tokens: int = 0         # entrada + saída das chamadas ao LLM; 0 na baseline
    custo_usd: float = 0    # 0 na baseline
    # D111: o que vai para o log sobre os limites de tempo
    estouro: str | None = None           # maven_inicial, teste_final ou caso
    causa: str | None = None             # causa da exclusão, quando `erro` é de infraestrutura
    tentativas_maven_inicial: int = 0
    duracao_caso_s: float | None = None  # contada para o limite do caso, sem a espera do LLM
    espera_llm_s: float = 0.0

    def para_o_log(self) -> dict:
        return {"estouro": self.estouro, "tentativas_maven_inicial": self.tentativas_maven_inicial,
                "duracao_caso_s": None if self.duracao_caso_s is None else round(self.duracao_caso_s, 2),
                "espera_llm_s": round(self.espera_llm_s, 2),
                "duracao_maven_s": [round(x, 2) for x in self.maven_s],
                "duracao_teste_s": [round(x, 2) for x in self.teste_s]}


def com_erro_de_execucao(entrada: "Entrada", exc: execucao.ErroDeExecucao) -> Execucao:
    """Registro de um caso que a infraestrutura não deixou rodar (fora das métricas, D111e)."""
    e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None, False,
                 exc.codigo, 0.0, causa=exc.causa)
    if exc.causa == "estouro_maven_inicial":
        e.estouro, e.tentativas_maven_inicial = "maven_inicial", 2
    return e


def rodar_final(e: Execucao, rodar, copia: Path, entrada: "Entrada", limite: execucao.LimiteDoCaso,
                limites: execucao.Limites) -> None:
    """Maven final do reparo aceito. O estouro é falha do tratamento (D111d): o agente decidiu
    reparar, então `decisao` fica `reparar` e o reparo conta como não compilado e não passado."""
    try:
        final = execucao.rodar_teste_final(rodar, copia, entrada.classe, entrada.metodo, limite, limites.teste_s)
    except execucao.ErroDeExecucao as exc:
        if exc.codigo != "timeout":
            raise
        e.compilou, e.passou, e.erro, e.estouro = False, False, "timeout", exc.causa
        return
    e.compilou, e.passou = final.compilou, final.passou
    e.maven_s.append(final.duracao_maven_s)
    e.teste_s.append(final.duracao_teste_s)


def exclusoes(log: list[dict]) -> dict:
    """Execuções fora das métricas (`erro_execucao` e `erro_llm`), com a causa e a contagem (D111e)."""
    lista = [{k: x[k] for k in ("id_caso", "repeticao", "erro", "causa")} for x in log
             if x["erro"] in ("erro_execucao", "erro_llm")]
    return {"exclusoes": lista, "exclusoes_por_causa": dict(Counter(x["causa"] for x in lista))}


def imprimir_exclusoes(dados: dict) -> None:
    contagem = ", ".join(f"{c}: {n}" for c, n in dados["exclusoes_por_causa"].items()) or "nenhuma"
    print(f"exclusões (fora das métricas): {len(dados['exclusoes'])} ({contagem})", flush=True)


# ---------------------------------------------------------------- execução (sem oráculo)

def executar_caso(entrada: Entrada, api: Path, tag: str, trabalho: Path,
                  rodar=execucao.rodar_teste, limites: execucao.Limites = execucao.Limites()) -> Execucao:
    copia = execucao.preparar_copia(api, tag, trabalho)
    try:
        antigo = contrato.carregar(copia / "docs" / "openapi.json")
        execucao.aplicar_patch(copia, entrada.patch)
        novo = contrato.carregar(copia / "docs" / "openapi.json")
        arquivo = execucao.arquivo_de_teste(copia, entrada.classe)
        original = arquivo.read_text(encoding="utf-8")
        rel = str(arquivo.relative_to(copia))

        inicial, tentativas = execucao.rodar_teste_inicial(rodar, copia, entrada.classe, entrada.metodo,
                                                           limites.teste_s)
        if inicial.passou:
            raise execucao.ErroDeExecucao(f"{entrada.id_caso}: o teste afetado passa sem reparo",
                                          causa="teste_passa_sem_reparo")
        limite = limites.caso()  # D111b: a partir da falha recebida
        e = Execucao(entrada.id_caso, entrada.classe, entrada.metodo, baseline.NAO_REPARAR, None,
                     False, None, 0.0, original=original, arquivo_relativo=rel,
                     maven_s=[inicial.duracao_maven_s], teste_s=[inicial.duracao_teste_s],
                     tentativas_maven_inicial=tentativas)

        inicio = time.monotonic()
        e.rotas = baseline.rotas_do_contrato(novo)
        e.mudancas = contrato.diferenca(antigo, novo)
        r = baseline.reparar(original, entrada.metodo, e.mudancas, e.rotas)
        e.aplicadas, e.ignoradas = len(r.aplicadas), [(m.caminho, motivo) for m, motivo in r.ignoradas]
        if r.decisao == baseline.REPARAR:
            veredito = guarda.avaliar(original, r.texto, entrada.metodo, e.mudancas, e.rotas)
            e.guarda_motivos = veredito.motivos
            if veredito.aceito:
                arquivo.write_text(r.texto, encoding="utf-8")
                e.decisao, e.reparado = baseline.REPARAR, r.texto
            else:
                e.erro = "guarda"
        e.tempo_s = time.monotonic() - inicio  # do recebimento da falha ao artefato final

        if e.decisao == baseline.REPARAR:
            rodar_final(e, rodar, copia, entrada, limite, limites)
        e.duracao_caso_s = limite.decorrido()
        return e
    finally:
        shutil.rmtree(copia, ignore_errors=True)


# ---------------------------------------------------------------- registro (com oráculo, depois)

def texto_esperado(raiz_repo: Path, correcao: str, rel_arquivo: str, original: str) -> str:
    """O arquivo de teste depois da correção esperada, aplicada num diretório temporário."""
    with tempfile.TemporaryDirectory() as d:
        alvo = Path(d, rel_arquivo)
        alvo.parent.mkdir(parents=True)
        alvo.write_text(original, encoding="utf-8")
        proc = subprocess.run(["git", "apply", str((raiz_repo / correcao).resolve())], cwd=d,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise execucao.ErroDeExecucao(f"correção esperada {correcao} não aplica: {proc.stderr}")
        return alvo.read_text(encoding="utf-8")


def registrar(e: Execucao, oraculo: dict, repeticao: int, raiz_repo: Path,
              tratamento: str = "baseline", versao_agente: str | None = None) -> tuple[dict, dict]:
    """Devolve (registro da D74, extras para o log). Único lugar que lê o oráculo.

    Os padrões de `tratamento` e `versao_agente` são os da baseline; a v1 passa `agentes` e `v1`.
    """
    registro = {"id_caso": e.id_caso, "agente": "agente1", "tratamento": tratamento,
                "versao_agente": versao_agente, "categoria": oraculo["categoria"],
                "rotulo_oraculo": oraculo["rotulo_oraculo"], "decisao": e.decisao,
                "compilou": None, "passou": e.passou, "equivalente_oraculo": None,
                "assercoes_enfraquecidas": None, "cenario_alterado": None,
                "repeticao": repeticao, "tempo_s": round(e.tempo_s, 4), "tokens": e.tokens,
                "custo_usd": e.custo_usd, "erro": e.erro}
    extras = {"revisao_manual": False, "motivos": []}
    if e.decisao == baseline.REPARAR:
        esperado = (texto_esperado(raiz_repo, oraculo["correcao_esperada"], e.arquivo_relativo,
                                   e.original) if oraculo["correcao_esperada"] else None)
        cmp = comparador.comparar(e.original, e.reparado, esperado, e.metodo, e.mudancas, e.rotas)
        registro.update(compilou=e.compilou, equivalente_oraculo=cmp.equivalente,
                        assercoes_enfraquecidas=False, cenario_alterado=cmp.cenario_alterado)
        extras["motivos"] = list(cmp.motivos)
        # Equivalente à correção esperada e com troca de cenário ao mesmo tempo não pode ser: a
        # correção esperada não troca o cenário. Quase sempre é a extração errando (T09, etapa 3).
        inconsistente = cmp.equivalente is True and cmp.cenario_alterado is True
        if inconsistente:
            extras["motivos"].append("inconsistência: equivalente ao oráculo e com troca de cenário")
        # D80: a regra que não decide, ou que reprova um reparo que compila e passa, vai para revisão manual
        extras["revisao_manual"] = bool(
            (esperado is not None and cmp.equivalente is None)
            or (cmp.equivalente is False and e.compilou and e.passou)
            or inconsistente)
        if extras["revisao_manual"]:
            # O veredito pendente fica no próprio arquivo: o script da T20a recusa o arquivo com
            # equivalente_oraculo nulo num caso legítimo reparado até a revisão manual preencher o valor.
            registro["equivalente_oraculo"] = None
    return registro, extras


def assinatura(registro: dict, reparado: str | None) -> tuple:
    """O que não pode variar entre repetições da baseline (tudo, menos o tempo)."""
    fixo = {k: v for k, v in registro.items() if k not in ("tempo_s", "repeticao")}
    return json.dumps(fixo, sort_keys=True), hashlib.sha256((reparado or "").encode()).hexdigest()


# ---------------------------------------------------------------- linha de comando

def _carregar_entradas(raiz_repo: Path, oraculo: dict, filtro: set[str] | None) -> list[Entrada]:
    entradas = []
    for caso in sorted(oraculo["casos"], key=lambda c: c["id_caso"]):
        if filtro and caso["id_caso"] not in filtro:
            continue
        classe, metodo = caso["teste_afetado"].split(".")
        entradas.append(Entrada(caso["id_caso"], (raiz_repo / caso["patch"]).resolve(), classe, metodo))
    return entradas


def adicionar_limites(ap: argparse.ArgumentParser) -> None:
    """Opções dos limites de tempo da D111, com os padrões dela; a v1 usa as mesmas."""
    ap.add_argument("--limite-teste-s", type=float, default=execucao.LIMITE_TESTE_S,
                    help="limite de uma chamada do mvnw, em segundos (D111a)")
    ap.add_argument("--limite-caso-s", type=float, default=execucao.LIMITE_CASO_S,
                    help="limite do caso, sem a espera do LLM, em segundos (D111b)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", required=True, type=Path, help="clone da API cobaia (rest-test-healing-sut)")
    ap.add_argument("--saida", required=True, type=Path, help="pasta de saída")
    ap.add_argument("--tag", default=TAG_PADRAO)
    ap.add_argument("--repeticoes", type=int, default=REPETICOES_PADRAO)
    ap.add_argument("--casos", nargs="*", help="ids de casos (padrão: todos)")
    adicionar_limites(ap)
    args = ap.parse_args(argv)

    raiz_repo = Path(__file__).resolve().parent.parent
    oraculo = json.loads((raiz_repo / "casos" / "oraculo-agente1.json").read_text(encoding="utf-8"))
    if oraculo["versao_api"] != args.tag:
        print(f"o oráculo é da tag {oraculo['versao_api']}, não de {args.tag}", file=sys.stderr)
        return 2
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    entradas = _carregar_entradas(raiz_repo, oraculo, set(args.casos) if args.casos else None)

    return executar_rodada(entradas, por_id, args.api, args.tag, raiz_repo, args.saida, args.repeticoes,
                           limites=execucao.Limites(args.limite_teste_s, args.limite_caso_s))


def executar_rodada(entradas: list[Entrada], por_id: dict, api: Path, tag: str, raiz_repo: Path, saida: Path,
                    repeticoes: int, rodar=execucao.rodar_teste,
                    limites: execucao.Limites = execucao.Limites()) -> int:
    registros, log, assinaturas = [], [], {}
    saida.mkdir(parents=True, exist_ok=True)
    print(f"limites: teste {limites.teste_s:g} s, caso {limites.caso_s:g} s (D111)", flush=True)
    with tempfile.TemporaryDirectory(prefix="baseline-") as trabalho:
        for entrada in entradas:
            for repeticao in range(1, repeticoes + 1):
                destino = Path(trabalho) / f"{entrada.id_caso}-r{repeticao}"
                try:
                    e = executar_caso(entrada, api, tag, destino, rodar, limites)
                except execucao.ErroDeExecucao as exc:
                    e = com_erro_de_execucao(entrada, exc)
                    print(f"{entrada.id_caso} r{repeticao}: ERRO {exc.codigo} ({exc.causa}): {exc}", flush=True)
                registro, extras = registrar(e, por_id[entrada.id_caso], repeticao, raiz_repo)
                registros.append(registro)
                assinaturas.setdefault(entrada.id_caso, set()).add(assinatura(registro, e.reparado))
                log.append({"id_caso": e.id_caso, "repeticao": repeticao, "erro": e.erro, "causa": e.causa,
                            "aplicadas": e.aplicadas, "ignoradas": e.ignoradas, "guarda": list(e.guarda_motivos),
                            **e.para_o_log(), **extras})
                resultados.gravar(saida / "resultados-agente1.json", tag, registros)
                print(f"{e.id_caso} r{repeticao}: {e.decisao} compilou={registro['compilou']} "
                      f"passou={registro['passou']} equivalente={registro['equivalente_oraculo']} "
                      f"cenario={registro['cenario_alterado']} erro={registro['erro']} estouro={e.estouro}",
                      flush=True)
    deterministica = {i: len(s) == 1 for i, s in assinaturas.items()}
    fora = exclusoes(log)
    (saida / "log-baseline.json").write_text(
        json.dumps({"limites": limites.para_o_log(), **fora, "deterministica": deterministica, "execucoes": log},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("determinística em todos os casos:", all(deterministica.values()))
    imprimir_exclusoes(fora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
