"""Ensaio da T23j (D105): os casos do piloto com o Maven de verdade e o LLM simulado, sem API paga.

O "aluno perfeito" segue um roteiro fixo e responde o que o oráculo espera, para provar que o
encanamento funciona de ponta a ponta: cópia, patch, Maven inicial, ferramentas (com o Maven de
verdade no rodar_teste), guarda, Maven final, registro e log. Isto é código de teste: só ele lê o
oráculo e a correção esperada; o runner e o agente nunca leem `casos/` além do patch.

Roteiro de cada caso:
- legítima: o Classifier pede ver_diferenca e responde `legitima`; o Repair salva o método da correção
  esperada, roda o teste e termina.
- problema real: o Classifier roda o teste e responde `problema_real`; o Repair não roda.
- agente único (T49), num laço só: na legítima, pede ver_diferenca, salva o método da correção esperada, roda o
  teste e responde `legitima`; no problema real, roda o teste e responde `problema_real`. No ensaio, ele roda
  nos 12 casos do piloto; na T25, o runner o roda só nos 8 sorteados (D97).

Uso, na raiz do repositório (PyCharm: veja o README):
    python -m tests.ensaio --api ../rest-test-healing-sut --saida resultados/t23j-ensaio

Ensaio da retomada (T53): `--interromper-em A1-007 1` derruba a rodada no meio dessa execução, depois do
`salvar_reparo` do Repair, como um Ctrl+C; depois, o mesmo comando com `--retomar` no lugar continua a rodada
na mesma `--saida`. Cada chamada do LLM simulado é gravada no `chamadas.jsonl`, com custo zero e
`request_id` "simulado", para a conta das chamadas sem registro aparecer.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from agente_contrato import execucao, rodar
from agente_contrato.registro_llm import LogDeChamadas
from agente_contrato.laco import PedidoFerramenta, RespostaModelo
from agente_contrato.teste_java import texto_do_metodo
from tests.llm_simulado import FabricaDupla, FabricaSimulada


def _pede(id_pedido: str, nome: str, **entrada) -> RespostaModelo:
    return RespostaModelo(f"vou usar {nome}", (PedidoFerramenta(id_pedido, nome, entrada),))


def _rotulo(valor: str) -> RespostaModelo:
    return RespostaModelo(json.dumps({"rotulo": valor, "justificativa": "ensaio com LLM simulado"}))


# D113: a correção esperada congelada do A1-007 (`.value("0")`) não verifica a mudança de tipo, e o guarda a
# recusa (matcher trocado por literal, D115). A correção que vale é `.value(is("0"))`; o oráculo congelado
# não muda (D96), e só o aluno perfeito do ensaio usa a correção da D113.
CORRECOES_D113 = {"A1-007": ('.value("0")', '.value(is("0"))')}


def metodo_esperado(caso: rodar.Caso, correcao: Path, api: Path, tag: str) -> str:
    """O método afetado depois da correção esperada, numa cópia descartável (só o ensaio faz isto)."""
    with tempfile.TemporaryDirectory() as d:
        copia = execucao.preparar_copia(api, tag, Path(d) / "c")
        execucao.aplicar_patch(copia, caso.patch)
        execucao.aplicar_patch(copia, correcao)
        arquivo = rodar.arquivo_de_teste(copia, caso.classe)
        metodo = texto_do_metodo((copia / arquivo).read_text(encoding="utf-8"), caso.metodo)
    if caso.id_caso in CORRECOES_D113:
        antigo, novo = CORRECOES_D113[caso.id_caso]
        if metodo.count(antigo) != 1:
            raise ValueError(f"{caso.id_caso}: a correção da D113 não se encaixa no método esperado")
        metodo = metodo.replace(antigo, novo)
    return metodo


def roteiro(caso: rodar.Caso, do_oraculo: dict, raiz_repo: Path, api: Path, tag: str) -> FabricaDupla:
    if do_oraculo["rotulo_oraculo"] == "problema_real":
        return FabricaDupla([_pede("c1", "rodar_teste"), _rotulo("problema_real")], [])
    metodo = metodo_esperado(caso, raiz_repo / do_oraculo["correcao_esperada"], api, tag)
    return FabricaDupla([_pede("c1", "ver_diferenca"), _rotulo("legitima")],
                        [_pede("r1", "salvar_reparo", metodo_reparado=metodo), _pede("r2", "rodar_teste"),
                         RespostaModelo("Reparo salvo e conferido.")])


def roteiro_agente_unico(caso: rodar.Caso, do_oraculo: dict, raiz_repo: Path, api: Path, tag: str) -> FabricaSimulada:
    if do_oraculo["rotulo_oraculo"] == "problema_real":
        return FabricaSimulada(_pede("u1", "rodar_teste"), _rotulo("problema_real"))
    metodo = metodo_esperado(caso, raiz_repo / do_oraculo["correcao_esperada"], api, tag)
    return FabricaSimulada(_pede("u1", "ver_diferenca"), _pede("u2", "salvar_reparo", metodo_reparado=metodo),
                           _pede("u3", "rodar_teste"), _rotulo("legitima"))


class Interrompido(KeyboardInterrupt):
    """A queda simulada do ensaio da retomada: nada no runner a trata, como um Ctrl+C."""


def com_log(fabrica, log: LogDeChamadas, id_caso: str, repeticao: int, cair: bool, tratamento: str = "agentes"):
    """Grava no `chamadas.jsonl` cada chamada do LLM simulado (custo zero), com o tratamento (T49); com `cair`,
    a rodada cai na segunda chamada do Repair, depois de o reparo ser salvo na cópia (só nos agentes)."""
    def criar(sistema, definicoes, formato=None):
        modelo = fabrica(sistema, definicoes, formato=formato)
        if tratamento == rodar.AGENTE_UNICO:
            etapa = "agente_unico"
        else:
            etapa = ("classifier", "repair")[len(fabrica.sistemas) - 1]
        feitas = []

        def chamar(historico):
            feitas.append(1)
            log.registrar(id_caso=id_caso, tratamento=tratamento, repeticao=repeticao, etapa=etapa, modelo_retornado="simulado",
                          stop_reason=None, input_tokens=0, output_tokens=0, thinking_tokens=None, custo_usd=0.0,
                          request_id="simulado", latencia_s=0.0, commit_do_prompt=None, resposta_bruta=None,
                          erro=None)
            if cair and etapa == "repair" and len(feitas) == 2:
                raise Interrompido(f"ensaio: rodada interrompida no meio de {id_caso} r{repeticao}")
            return modelo(historico)
        return chamar
    return criar


def conferir(pasta: Path) -> bool:
    """Cada execução dos agentes e do agente único deve sair como o oráculo espera, sem erro de infraestrutura.

    A baseline (T51) não segue roteiro: ela erra as regressões por desenho (D75). Aqui só se confere que ela
    rodou sem erro de infraestrutura; a comparação com a v1 é a de tests/comparar_t42.py.
    """
    registros = json.loads((pasta / rodar.ARQUIVO_RESULTADOS).read_text(encoding="utf-8"))["execucoes"]
    ok = True
    for r in registros:
        if r["tratamento"] == rodar.BASELINE:
            sem_infra = r["erro"] not in ("erro_execucao", "erro_llm")
            ok = ok and sem_infra
            print("OK   " if sem_infra else "FALHA", r["id_caso"], "baseline", r["rotulo_oraculo"], r["decisao"],
                  r["compilou"], r["passou"], r["erro"])
            continue
        if r["rotulo_oraculo"] == "legitima":
            esperado = (r["decisao"], r["compilou"], r["passou"], r["erro"]) == ("reparar", True, True, None)
        else:
            esperado = (r["decisao"], r["compilou"], r["passou"], r["erro"]) == ("nao_reparar", None, False, None)
        ok = ok and esperado
        print("OK   " if esperado else "FALHA", r["id_caso"], r["tratamento"], r["rotulo_oraculo"], r["decisao"],
              r["compilou"],
              r["passou"], r["erro"], f"{r['tempo_s']:.1f} s")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensaio da T23j e da T49 com o Maven de verdade e o LLM simulado")
    ap.add_argument("--api", required=True, type=Path)
    ap.add_argument("--saida", required=True, type=Path)
    ap.add_argument("--repeticoes", type=int, default=1, help="repetições nos agentes; a baseline roda 1 vez (D92)")
    ap.add_argument("--tratamentos", nargs="+", choices=rodar.ORDEM_DOS_TRATAMENTOS,
                    default=list(rodar.ORDEM_DOS_TRATAMENTOS),
                    help="padrão: os três, na ordem da D82; o agente único roda em todos os casos do ensaio")
    ap.add_argument("--casos", nargs="*", help="ids dos casos (padrão: os 12 do piloto)")
    ap.add_argument("--retomar", action="store_true", help="continua a rodada interrompida na mesma --saida (T53)")
    ap.add_argument("--interromper-em", nargs=2, metavar=("CASO", "REPETICAO"),
                    help="derruba a rodada no meio desta execução, para o ensaio da retomada (T53)")
    args = ap.parse_args()
    raiz_repo = rodar.RAIZ_REPO
    do_oraculo = rodar.oraculo_do_log(rodar.ORACULO_PADRAO)
    oraculo = json.loads((raiz_repo / do_oraculo["arquivo"]).read_text(encoding="utf-8"))
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    tag = oraculo["versao_api"]
    commits = rodar.commits_atuais()
    try:
        anteriores = rodar.carregar_anteriores(args.saida, args.retomar,
                                               rodar.cabecalho(tag, do_oraculo, commits, rodar.LIMITE_CASO_S))
    except rodar.RetomadaInvalida as exc:
        print(f"o ensaio não roda: {exc}", file=sys.stderr)
        return 2
    cair_em = (args.interromper_em[0], int(args.interromper_em[1])) if args.interromper_em else None
    log = LogDeChamadas(args.saida / rodar.ARQUIVO_CHAMADAS)
    casos = rodar.carregar_casos(oraculo, ids=set(args.casos) if args.casos else None)
    roteiros = {c.id_caso: (c, por_id[c.id_caso]) for c in casos}

    def criar_fabrica(id_caso: str, repeticao: int, tratamento: str):
        caso, do_caso = roteiros[id_caso]
        if tratamento == rodar.AGENTE_UNICO:
            return com_log(roteiro_agente_unico(caso, do_caso, raiz_repo, args.api, tag), log, id_caso, repeticao,
                           False, tratamento)
        return com_log(roteiro(caso, do_caso, raiz_repo, args.api, tag), log, id_caso, repeticao,
                       (id_caso, repeticao) == cair_em)

    codigo = rodar.executar_rodada(casos, por_id, args.api, tag, args.saida, args.repeticoes, criar_fabrica,
                                   commits, oraculo=do_oraculo, anteriores=anteriores,
                                   tratamentos=tuple(args.tratamentos))
    ok = codigo == rodar.SAIDA_OK and conferir(args.saida)
    print("ENSAIO", "OK" if ok else "FALHOU", f"(código de saída do runner: {codigo})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
