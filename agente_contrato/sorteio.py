"""Sorteio dos casos do agente único (T49, D97): um legítimo e uma regressão por categoria, com semente fixa.

Tudo aqui é código determinístico, sem LLM. Do oráculo, só se leem o `id_caso`, a `categoria` e o
`rotulo_oraculo`; o resultado é gravado num arquivo versionado, num commit anterior a qualquer execução.

Uso, na raiz do repositório:

    python -m agente_contrato.sorteio --semente 4949
"""
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from agente_contrato import prompts

RAIZ_REPO = Path(__file__).resolve().parent.parent
ORACULO_FINAL = RAIZ_REPO / "casos" / "oraculo-agente1-final.json"
ARQUIVO_SORTEIO = RAIZ_REPO / "casos" / "sorteio-agente-unico.json"
TAG_DO_ORACULO = "oraculo-final"  # D96, T48

# A ordem fixa das combinações: a mesma semente sempre dá os mesmos casos.
CATEGORIAS = ("renomeacao", "remocao", "alteracao_tipo", "campo_obrigatorio_novo")  # D91
ROTULOS = ("legitima", "problema_real")
METODO = ("para cada (categoria, rotulo), nesta ordem, os id_caso em ordem crescente e um random.Random(semente)"
          ".choice, o mesmo gerador para as 8 combinações")


def sortear(casos: list[dict], semente: int) -> list[dict]:
    """Um caso por (categoria, rótulo), na ordem de CATEGORIAS e ROTULOS (D97).

    Lê de cada caso só `id_caso`, `categoria` e `rotulo_oraculo`. Uma combinação sem caso para o sorteio.
    """
    gerador = random.Random(semente)
    escolhidos = []
    for categoria in CATEGORIAS:
        for rotulo in ROTULOS:
            ids = sorted(c["id_caso"] for c in casos
                         if c["categoria"] == categoria and c["rotulo_oraculo"] == rotulo)
            if not ids:
                raise ValueError(f"nenhum caso com categoria {categoria} e rótulo {rotulo}")
            escolhidos.append({"categoria": categoria, "rotulo_oraculo": rotulo, "candidatos": ids,
                               "id_caso": gerador.choice(ids)})
    return escolhidos


def ids_sorteados(sorteio: dict) -> set[str]:
    """Os IDs de um arquivo de sorteio já gravado."""
    return {e["id_caso"] for e in sorteio["sorteados"]}


def commit_da_tag(tag: str) -> str:
    """O commit para o qual a tag aponta, para o arquivo do sorteio dizer de que oráculo saiu."""
    r = subprocess.run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=RAIZ_REPO, capture_output=True, text=True,
                       check=True)
    return r.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--semente", type=int, required=True)
    ap.add_argument("--gravar", action="store_true", help="grava o arquivo do sorteio; sem isso, só mostra")
    args = ap.parse_args(argv)
    oraculo = json.loads(ORACULO_FINAL.read_text(encoding="utf-8"))
    sorteados = sortear(oraculo["casos"], args.semente)
    dados = {"tarefa": "T49", "decisao": "D97", "semente": args.semente, "metodo": METODO,
             "oraculo": {"arquivo": ORACULO_FINAL.relative_to(RAIZ_REPO).as_posix(),
                         "commit": prompts.commit_dos_prompts(ORACULO_FINAL),
                         "tag": TAG_DO_ORACULO, "commit_da_tag": commit_da_tag(TAG_DO_ORACULO)},
             "sorteados": sorteados, "ids": sorted(e["id_caso"] for e in sorteados)}
    texto = json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    print(texto, end="")
    if args.gravar:
        ARQUIVO_SORTEIO.write_text(texto, encoding="utf-8")
        print(f"gravado em {ARQUIVO_SORTEIO.relative_to(RAIZ_REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
