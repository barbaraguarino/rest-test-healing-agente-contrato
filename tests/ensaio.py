"""Ensaio da T23j (D105): os casos do piloto com o Maven de verdade e o LLM simulado, sem API paga.

O "aluno perfeito" segue um roteiro fixo e responde o que o oráculo espera, para provar que o
encanamento funciona de ponta a ponta: cópia, patch, Maven inicial, ferramentas (com o Maven de
verdade no rodar_teste), guarda, Maven final, registro e log. Isto é código de teste: só ele lê o
oráculo e a correção esperada; o runner e o agente nunca leem `casos/` além do patch.

Roteiro de cada caso:
- legítima: o Classifier pede ver_diferenca e responde `legitima`; o Repair salva o método da correção
  esperada, roda o teste e termina.
- problema real: o Classifier roda o teste e responde `problema_real`; o Repair não roda.

Uso, na raiz do repositório (PyCharm: veja o README):
    python -m tests.ensaio --api ../rest-test-healing-sut --saida resultados/t23j-ensaio
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from agente_contrato import execucao, rodar
from agente_contrato.laco import PedidoFerramenta, RespostaModelo
from agente_contrato.teste_java import texto_do_metodo
from tests.llm_simulado import FabricaDupla


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


def conferir(pasta: Path) -> bool:
    """Cada execução deve sair como o oráculo espera, sem erro de infraestrutura."""
    registros = json.loads((pasta / rodar.ARQUIVO_RESULTADOS).read_text(encoding="utf-8"))["execucoes"]
    ok = True
    for r in registros:
        if r["rotulo_oraculo"] == "legitima":
            esperado = (r["decisao"], r["compilou"], r["passou"], r["erro"]) == ("reparar", True, True, None)
        else:
            esperado = (r["decisao"], r["compilou"], r["passou"], r["erro"]) == ("nao_reparar", None, False, None)
        ok = ok and esperado
        print("OK   " if esperado else "FALHA", r["id_caso"], r["rotulo_oraculo"], r["decisao"], r["compilou"],
              r["passou"], r["erro"], f"{r['tempo_s']:.1f} s")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensaio da T23j com o Maven de verdade e o LLM simulado")
    ap.add_argument("--api", required=True, type=Path)
    ap.add_argument("--saida", required=True, type=Path)
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--casos", nargs="*", help="ids dos casos (padrão: os 12 do piloto)")
    args = ap.parse_args()
    if (args.saida / rodar.ARQUIVO_RESULTADOS).exists():
        print(f"{args.saida} já tem uma rodada; escolha outra --saida", file=sys.stderr)
        return 2
    raiz_repo = rodar.RAIZ_REPO
    oraculo = json.loads((raiz_repo / "casos" / "oraculo-agente1.json").read_text(encoding="utf-8"))
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    tag = oraculo["versao_api"]
    casos = rodar.carregar_casos(oraculo, ids=set(args.casos) if args.casos else None)
    roteiros = {c.id_caso: (c, por_id[c.id_caso]) for c in casos}

    def criar_fabrica(id_caso: str, repeticao: int):
        caso, do_oraculo = roteiros[id_caso]
        return roteiro(caso, do_oraculo, raiz_repo, args.api, tag)

    codigo = rodar.executar_rodada(casos, por_id, args.api, tag, args.saida, args.repeticoes, criar_fabrica,
                                   rodar.commits_atuais())
    ok = codigo == rodar.SAIDA_OK and conferir(args.saida)
    print("ENSAIO", "OK" if ok else "FALHOU", f"(código de saída do runner: {codigo})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
