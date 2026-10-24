"""Ensaio da etapa 0 da D105: os 4 casos da etapa 3 com o Maven de verdade e um modelo falso.

Não chama a API paga e não usa chave. O "modelo perfeito" responde o que o oráculo espera, para
provar que o encanamento (cópia, patch, evidência, validação, encaixe, guarda, Maven, registro)
funciona de ponta a ponta. Isto é código de teste: o agente em si nunca lê `casos/` além do patch.

Uso, na raiz do repositório:
    python -m tests.ensaio_etapa0 --api ../rest-test-healing-sut --saida CAMINHO
    python -m tests.ensaio_etapa0 --piloto [--repeticoes 3] [--retomar] --api ... --saida CAMINHO

`--piloto` é o ensaio da etapa 4: os 12 casos, com o aquecimento do Maven e a retomada da pasta.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from agente_contrato import evidencia, execucao, prompts, rodar_baseline, rodar_v1
from agente_contrato.registro_llm import LogDeChamadas, Orcamento

from .fakes import ClienteFalso, classificacao, reparo


def metodo_esperado(entrada, oraculo, api: Path, tag: str, raiz_repo: Path) -> str:
    with tempfile.TemporaryDirectory() as d:
        copia = execucao.preparar_copia(api, tag, Path(d) / "c")
        execucao.aplicar_patch(copia, entrada.patch)
        arquivo = execucao.arquivo_de_teste(copia, entrada.classe)
        esperado = rodar_baseline.texto_esperado(raiz_repo, oraculo["correcao_esperada"],
                                                 str(arquivo.relative_to(copia)), arquivo.read_text(encoding="utf-8"))
        return evidencia.texto_do_metodo(esperado, entrada.metodo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True, type=Path)
    ap.add_argument("--saida", required=True, type=Path)
    ap.add_argument("--piloto", action="store_true", help="os 12 casos, como a etapa 4")
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--retomar", action="store_true")
    args = ap.parse_args()
    raiz_repo = Path(__file__).resolve().parent.parent
    oraculo = json.loads((raiz_repo / "casos" / "oraculo-agente1.json").read_text(encoding="utf-8"))
    por_id = {c["id_caso"]: c for c in oraculo["casos"]}
    ids = tuple(sorted(por_id)) if args.piloto else rodar_v1.CASOS_DA_ETAPA_3
    entradas = rodar_baseline._carregar_entradas(raiz_repo, oraculo, set(ids))
    entradas.sort(key=lambda e: ids.index(e.id_caso))
    commit, codigo_do_codigo = prompts.commit_dos_prompts(), rodar_v1.commit_do_codigo()
    limites = execucao.Limites(llm_s=rodar_v1.chamada_llm.TIMEOUT_S)
    anteriores = (rodar_v1.carregar_anteriores(args.saida, oraculo["versao_api"], args.retomar, commit,
                                               codigo_do_codigo, limites) if args.piloto else None)
    feitos = anteriores.feitos() if anteriores else set()

    roteiro = []
    for e in entradas:
        c = por_id[e.id_caso]
        for rep in range(1, args.repeticoes + 1):
            if (e.id_caso, rep) in feitos:
                continue
            if c["rotulo_oraculo"] == "legitima":
                roteiro += [classificacao("legitima", "ensaio"),
                            reparo(metodo_esperado(e, c, args.api, oraculo["versao_api"], raiz_repo))]
            else:
                roteiro.append(classificacao("problema_real", "ensaio"))

    textos = {n: prompts.carregar(n) for n in ("classifier", "repair")}
    chamador = rodar_v1.Chamador(ClienteFalso(roteiro), LogDeChamadas(args.saida / "chamadas.jsonl"),
                                 Orcamento(1.0), textos, commit)
    codigo = rodar_v1.executar_rodada(entradas, por_id, args.api, oraculo["versao_api"], raiz_repo, args.saida,
                                      args.repeticoes, chamador, commit_codigo=codigo_do_codigo, limites=limites,
                                      anteriores=anteriores, aquecer_antes=args.piloto)

    registros = json.loads((args.saida / "resultados-agente1.json").read_text(encoding="utf-8"))["execucoes"]
    ok = codigo == 0 and len(registros) == len(entradas) * args.repeticoes
    for r in registros:
        esperado = ((r["decisao"], r["passou"], r["equivalente_oraculo"]) == ("nao_reparar", False, None)
                    if r["rotulo_oraculo"] == "problema_real"
                    else (r["decisao"], r["compilou"], r["passou"], r["equivalente_oraculo"]) == ("reparar", True, True, True))
        ok = ok and esperado and r["erro"] is None
        print(("OK  " if esperado else "FALHA"), r["id_caso"], r["rotulo_oraculo"], r["decisao"], r["compilou"], r["passou"], r["equivalente_oraculo"], r["erro"])
    print("ENSAIO", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
