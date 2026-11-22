"""Aplica o comparador (T50) a uma pasta de resultados já gravada, sem Maven e sem LLM.

Preenche, no próprio `resultados-agente1.json` (decisão da T50), `equivalente_oraculo` e `cenario_alterado` das
execuções com `decisao=reparar`, e grava ao lado o `comparacao.json`, com a regra da D95, os motivos e a
revisão manual de cada uma (o log da D110). Nenhum outro campo muda.

- Revisão manual (D80, D109): `equivalente_oraculo` fica nulo (D110) até a Barbara gravar true ou false, com
  o motivo no `comparacao.json`. Rodar de novo não apaga o veredito gravado por ela.
- Regressão reparada (D119): sem correção esperada, `equivalente_oraculo` fica nulo; `cenario_alterado` é
  preenchido.

A correção esperada e a diferença de contrato saem de uma cópia descartável da API cobaia, na tag do log:
patch do caso e depois a correção esperada, só com o Git (como em `tests/ensaio.py`, sem a correção da D113:
vale o oráculo congelado, D96).

Uso, na raiz do repositório:
    python -m agente_contrato.comparar_resultados --api ../rest-test-healing-sut --pasta resultados/t25-final
"""
import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import comparador, execucao, ferramentas, registro, rodar
from .contrato import Mudanca, diferenca, rotas_do_contrato
from .teste_java import texto_do_metodo

ARQUIVO_COMPARACAO = "comparacao.json"
CAMPOS_DO_COMPARADOR = ("equivalente_oraculo", "cenario_alterado")


@dataclass(frozen=True)
class DoCaso:
    """O que o comparador precisa de um caso, igual em todas as execuções dele."""
    metodo: str
    esperado: str | None  # o método depois da correção esperada; None numa regressão
    mudancas: list[Mudanca]
    rotas: dict[str, set[str]]


def preparar_caso(item: dict, api: Path, tag: str, raiz_repo: Path) -> DoCaso:
    """Cópia descartável da API na tag, com o patch do caso; a correção esperada vem por cima, se houver."""
    classe, metodo = item["teste_afetado"].split(".")
    with tempfile.TemporaryDirectory() as d:
        copia = execucao.preparar_copia(api, tag, Path(d) / "c")
        execucao.aplicar_patch(copia, (raiz_repo / item["patch"]).resolve())
        antigo, novo = ferramentas.contratos(copia)
        esperado = None
        if item.get("correcao_esperada"):
            execucao.aplicar_patch(copia, (raiz_repo / item["correcao_esperada"]).resolve())
            arquivo = rodar.arquivo_de_teste(copia, classe)
            esperado = texto_do_metodo((copia / arquivo).read_text(encoding="utf-8"), metodo)
    return DoCaso(metodo, esperado, diferenca(antigo, novo), rotas_do_contrato(novo))


def comparar_execucao(r: dict, pasta_execucao: Path, caso: DoCaso) -> tuple[dict, dict]:
    """Devolve (os dois campos do comparador, a entrada do comparacao.json) de uma execução reparada."""
    antes = (pasta_execucao / "antes.java").read_text(encoding="utf-8")
    depois = (pasta_execucao / "depois.java").read_text(encoding="utf-8")
    cmp = comparador.comparar(antes, depois, caso.esperado, caso.metodo, caso.mudancas, caso.rotas)
    revisao = comparador.revisao_manual(cmp, caso.esperado is not None, r["compilou"], r["passou"],
                                        r["assercoes_enfraquecidas"])
    campos = {"equivalente_oraculo": None if revisao else cmp.equivalente,
              "cenario_alterado": cmp.cenario_alterado}
    entrada = {"id_caso": r["id_caso"], "tratamento": r["tratamento"], "repeticao": r["repeticao"],
               "pasta": pasta_execucao.name, "rotulo_oraculo": r["rotulo_oraculo"],
               "equivalente_regra": cmp.equivalente, "regra": cmp.regra,
               "cenario_alterado": cmp.cenario_alterado, "motivos": list(cmp.motivos),
               "revisao_manual": revisao, "veredito_manual": None, "motivo_do_veredito": None}
    return campos, entrada


def _mesclar(r: dict, campos: dict, anterior: dict | None) -> dict:
    """Preenche os dois campos sem sobrescrever o que já está gravado com outro valor.

    A única exceção é a revisão manual: o veredito que a Barbara gravou (D110) fica, e o comparador não o
    toca. Qualquer outra divergência para a ferramenta, porque o comparador é determinístico.
    """
    novo = dict(r)
    for campo, valor in campos.items():
        if r[campo] is None or r[campo] == valor:
            novo[campo] = valor if r[campo] is None else r[campo]
            continue
        manual = (campo == "equivalente_oraculo" and anterior and anterior.get("revisao_manual")
                  and anterior.get("veredito_manual") == r[campo])
        if not manual:
            raise ValueError(f"{r['id_caso']} {r['tratamento']} r{r['repeticao']}: {campo} já gravado "
                             f"como {r[campo]!r}, e o comparador dá {valor!r}")
    return novo


def chave(x: dict) -> tuple:
    return x["id_caso"], x["tratamento"], x["repeticao"]


def aplicar(pasta: Path, api: Path, raiz_repo: Path = rodar.RAIZ_REPO, oraculo: Path | None = None) -> list[dict]:
    """Compara todas as execuções reparadas da pasta e grava os dois arquivos; devolve o comparacao.json."""
    log = json.loads((pasta / rodar.ARQUIVO_LOG).read_text(encoding="utf-8"))
    if oraculo is None:  # o log da T53 em diante grava o oráculo; antes dela, só havia o do piloto
        oraculo = raiz_repo / (log.get("oraculo") or {}).get("arquivo", "casos/oraculo-agente1.json")
    oraculo = oraculo.resolve()
    itens = {c["id_caso"]: c for c in json.loads(oraculo.read_text(encoding="utf-8"))["casos"]}
    arquivo = pasta / rodar.ARQUIVO_RESULTADOS
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    caminho_cmp = pasta / ARQUIVO_COMPARACAO
    anteriores = ({chave(x): x for x in json.loads(caminho_cmp.read_text(encoding="utf-8"))["execucoes"]}
                  if caminho_cmp.exists() else {})

    casos, registros, entradas = {}, [], []
    for r in dados["execucoes"]:
        if r["decisao"] != "reparar":
            registros.append(r)
            continue
        if r["id_caso"] not in casos:
            casos[r["id_caso"]] = preparar_caso(itens[r["id_caso"]], api, log["tag"], raiz_repo)
        pasta_execucao = pasta / "execucoes" / rodar.nome_da_execucao(r["id_caso"], r["tratamento"], r["repeticao"])
        campos, entrada = comparar_execucao(r, pasta_execucao, casos[r["id_caso"]])
        anterior = anteriores.get(chave(r))
        if anterior:  # o veredito manual e o motivo dela ficam de uma rodada para outra
            entrada.update(veredito_manual=anterior.get("veredito_manual"),
                           motivo_do_veredito=anterior.get("motivo_do_veredito"))
        registros.append(_mesclar(r, campos, anterior))
        entradas.append(entrada)

    for antigo, novo in zip(dados["execucoes"], registros):  # só os dois campos do comparador podem mudar
        mudou = {c for c in antigo if antigo[c] != novo[c]}
        if mudou - set(CAMPOS_DO_COMPARADOR):
            raise AssertionError(f"campos fora do comparador mudaram: {sorted(mudou)}")

    registro.gravar_resultados(arquivo, dados["versao_api"], registros)
    caminho_cmp.write_text(json.dumps({"oraculo": oraculo.relative_to(raiz_repo).as_posix(), "tag": log["tag"],
                                       "execucoes": entradas}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return entradas


def resumo(entradas: list[dict]) -> str:
    """Quantas execuções por regra (1, 2, 3, não equivalente, revisão manual), nas legítimas e nas regressões."""
    linhas = []
    for rotulo in ("legitima", "problema_real"):
        grupo = [e for e in entradas if e["rotulo_oraculo"] == rotulo]
        if not grupo:
            continue
        revisao = [e for e in grupo if e["revisao_manual"]]
        decididas = [e for e in grupo if not e["revisao_manual"]]
        conta = {f"regra {n}": sum(e["regra"] == n for e in decididas) for n in (1, 2, 3)}
        conta["não equivalente"] = sum(e["equivalente_regra"] is False for e in decididas)
        conta["sem correção esperada"] = sum(e["equivalente_regra"] is None for e in decididas)
        conta["revisão manual"] = len(revisao)
        conta["cenário alterado"] = sum(e["cenario_alterado"] is True for e in grupo)
        linhas.append(f"{rotulo} ({len(grupo)} reparadas): "
                      + ", ".join(f"{k} {v}" for k, v in conta.items() if v or k.startswith("regra")))
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", required=True, type=Path, help="clone da API cobaia (rest-test-healing-sut)")
    ap.add_argument("--pasta", required=True, type=Path, help="pasta da rodada, com resultados-agente1.json")
    ap.add_argument("--oraculo", type=Path, help="padrão: o oráculo gravado no log da rodada")
    args = ap.parse_args(argv)
    entradas = aplicar(args.pasta, args.api, oraculo=args.oraculo)
    print(resumo(entradas))
    for e in entradas:
        if e["revisao_manual"]:
            print(f"revisão manual: {e['pasta']} ({e['tratamento']}): {e['revisao_manual']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
