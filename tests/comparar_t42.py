"""Compara o ensaio da baseline nova (T51) com a baseline da v1 (t42-baseline, tag rodada-2). Sem LLM e sem API.

Duas comparações, caso a caso:
1. Resultado: `decisao`, `compilou`, `passou` e `erro` do ensaio contra a repetição 1 da t42
   (`resultados/t42-baseline/resultados-agente1.json` da tag rodada-2; as 3 repetições de lá são iguais).
   `equivalente_oraculo` e `cenario_alterado` não entram: aqui saem nulos, porque o comparador (T50) ainda
   não existe; os da t42 são mostrados para referência, com os de `metricas-corrigido-d113.json` (D113).
2. Reparo: o método afetado que a baseline nova gravou (`execucoes/A1-NNN-baseline-r1/depois.java`) contra o
   que a baseline da v1 gera no mesmo caso. O código da v1 (baseline.py, contrato.py e teste_java.py da tag
   rodada-2) é extraído para uma pasta temporária e roda só em Python, sobre uma cópia da API com o patch,
   sem Maven. A diferença de contrato das duas versões também é comparada.

Toda diferença tem de ser explicada pela D114 (`.value(is(0))` -> `.value(is("0"))`); as explicadas ficam
em ESPERADAS. Qualquer outra faz o script terminar com código 1.

Uso, na raiz do repositório, depois do ensaio (PyCharm: veja o README):
    python -m tests.comparar_t42 --api ../rest-test-healing-sut --ensaio resultados/t51-ensaio
"""
import argparse
import dataclasses
import difflib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agente_contrato import execucao, rodar
from agente_contrato.contrato import diferenca
from agente_contrato.ferramentas import contratos
from agente_contrato.teste_java import texto_do_metodo

TAG_V1 = "rodada-2"
T42 = "resultados/t42-baseline"
CAMPOS = ("decisao", "compilou", "passou", "erro")

# A única diferença de reparo esperada: a alteração de tipo na resposta (D114). A v1 gerava o literal.
ESPERADAS = {"A1-007": ('.value("0")', '.value(is("0"))')}


def da_tag(caminho: str) -> str:
    return subprocess.run(["git", "show", f"{TAG_V1}:{caminho}"], cwd=rodar.RAIZ_REPO, capture_output=True,
                          text=True, check=True).stdout


def carregar_v1(pasta: Path):
    """O pacote da v1 (só os 3 módulos que a baseline usa), importado com outro nome."""
    pacote = pasta / "baseline_v1"
    pacote.mkdir()
    (pacote / "__init__.py").write_text("", encoding="utf-8")
    for nome in ("baseline", "contrato", "teste_java"):
        (pacote / f"{nome}.py").write_text(da_tag(f"agente_contrato/{nome}.py"), encoding="utf-8")
    sys.path.insert(0, str(pasta))
    try:
        return importlib.import_module("baseline_v1.baseline"), importlib.import_module("baseline_v1.contrato")
    finally:
        sys.path.pop(0)


def reparo_v1(caso: rodar.Caso, api: Path, tag: str, trabalho: Path, b1, c1) -> tuple[str, list[str], list[str]]:
    """O método afetado depois da baseline da v1, e as mudanças de contrato da v1 e da develop."""
    copia = execucao.preparar_copia(api, tag, trabalho)
    try:
        execucao.aplicar_patch(copia, caso.patch)
        arquivo = rodar.arquivo_de_teste(copia, caso.classe)
        original = (copia / arquivo).read_bytes().decode("utf-8")
        antigo, novo = contratos(copia)
        mudancas_v1 = c1.diferenca(antigo, novo)
        r = b1.reparar(original, caso.metodo, mudancas_v1, c1.rotas_do_contrato(novo))
        nova = sorted(repr(dataclasses.astuple(m)) for m in diferenca(antigo, novo))
        v1 = sorted(repr(dataclasses.astuple(m)) for m in mudancas_v1)
        return texto_do_metodo(r.texto, caso.metodo), v1, nova
    finally:
        shutil.rmtree(copia, ignore_errors=True)


def comparar(api: Path, ensaio: Path) -> dict:
    oraculo = json.loads(rodar.ORACULO_PADRAO.read_text(encoding="utf-8"))
    casos = rodar.carregar_casos(oraculo)
    t42 = {r["id_caso"]: r for r in json.loads(da_tag(f"{T42}/resultados-agente1.json"))["execucoes"]
           if r["repeticao"] == 1}
    nossos = {r["id_caso"]: r for r in json.loads((ensaio / rodar.ARQUIVO_RESULTADOS).read_text(encoding="utf-8"))
              ["execucoes"] if r["tratamento"] == rodar.BASELINE}
    linhas, inexplicadas = [], []
    with tempfile.TemporaryDirectory(prefix="t42-") as d:
        b1, c1 = carregar_v1(Path(d))
        for caso in casos:
            i = caso.id_caso
            nosso, antigo = nossos.get(i), t42.get(i)
            if nosso is None or antigo is None:
                inexplicadas.append(f"{i}: falta no ensaio ou na t42")
                continue
            depois = (ensaio / "execucoes" / f"{i}-baseline-r1" / "depois.java").read_text(encoding="utf-8")
            metodo_v1, mud_v1, mud_nova = reparo_v1(caso, api, oraculo["versao_api"], Path(d) / i, b1, c1)
            diff = list(difflib.unified_diff(metodo_v1.splitlines(), depois.splitlines(), "v1", "t51", lineterm="",
                                             n=0))
            campos = {k: (antigo[k], nosso[k]) for k in CAMPOS if antigo[k] != nosso[k]}
            explicada = None
            if diff:
                de, para = ESPERADAS.get(i, (None, None))
                explicada = de is not None and metodo_v1.replace(de, para) == depois
                if not explicada:
                    inexplicadas.append(f"{i}: reparo diferente da v1 sem explicação")
            if campos:
                inexplicadas.append(f"{i}: resultado diferente da t42 em {sorted(campos)}")
            if mud_v1 != mud_nova:
                inexplicadas.append(f"{i}: diferença de contrato da v1 e da develop não batem")
            linhas.append({"id_caso": i, "rotulo_oraculo": nosso["rotulo_oraculo"], "categoria": nosso["categoria"],
                           **{k: nosso[k] for k in CAMPOS},
                           "campos_diferentes_da_t42": {k: list(v) for k, v in campos.items()},
                           "equivalente_oraculo_t42": antigo["equivalente_oraculo"],
                           "reparo_igual_ao_da_v1": not diff, "diferenca_do_reparo": diff,
                           "explicada_pela_d114": explicada, "mudancas_de_contrato_iguais": mud_v1 == mud_nova})
    return {"comparado_com": f"{TAG_V1}:{T42}/resultados-agente1.json (repetição 1)", "casos": linhas,
            "diferencas_sem_explicacao": inexplicadas}


def main() -> int:
    ap = argparse.ArgumentParser(description="Compara o ensaio da baseline (T51) com a t42-baseline da v1")
    ap.add_argument("--api", required=True, type=Path)
    ap.add_argument("--ensaio", required=True, type=Path)
    args = ap.parse_args()
    dados = comparar(args.api, args.ensaio)
    (args.ensaio / "comparacao-t42.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
    for x in dados["casos"]:
        estado = "igual" if x["reparo_igual_ao_da_v1"] else ("D114" if x["explicada_pela_d114"] else "DIFERENTE")
        print(f"{x['id_caso']} {x['rotulo_oraculo']:13} {x['decisao']:11} compilou={x['compilou']} "
              f"passou={x['passou']} erro={x['erro']} | reparo: {estado} | t42: {x['campos_diferentes_da_t42'] or 'igual'}")
        for linha in x["diferenca_do_reparo"]:
            if linha.startswith(("+", "-")) and not linha.startswith(("+++", "---")):
                print("      ", linha.strip())
    if dados["diferencas_sem_explicacao"]:
        print("DIFERENÇAS SEM EXPLICAÇÃO:", *dados["diferencas_sem_explicacao"], sep="\n  ")
        return 1
    print("COMPARAÇÃO OK: só a diferença da D114")
    return 0


if __name__ == "__main__":
    sys.exit(main())
