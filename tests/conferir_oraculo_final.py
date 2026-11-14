"""Conferência dos 24 casos finais do Agente 1 (T48), sem LLM e sem API paga (D99).

Não usa o runner nem o laço do agente: só o Maven, o `contrato.py` e o `guarda.py`. Para CADA caso:
  a. o patch aplica sobre a tag `linha-de-base-2`;
  b. o teste afetado FALHA depois do patch (rodando sozinho, como o runner faz);
  c. legítimo: a correção esperada aplica, o teste PASSA e o `guarda.avaliar` ACEITA (D115, D116, D77);
  d. regressão: a diferença de contrato não é vazia (D76), a parte legítima e a parte não registrada
     atingem o MESMO teste (D93) e, corrigida só a parte legítima, o teste continua falhando;
  e. o `contrato.diferenca` classifica a mudança na categoria pretendida (D122).
Informativo (não reprova): os outros testes da suíte que o patch também quebra.

O que cada caso deve produzir está em `tests/conferencia_final.json`; o gabarito em si é o oráculo.

Uso, na raiz do repositório (PyCharm: botão direito no arquivo, Run):
    python -m tests.conferir_oraculo_final --api ../rest-test-healing-sut --saida resultados/t48-conferencia
"""
import argparse
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agente_contrato import contrato as c
from agente_contrato import execucao, guarda
from agente_contrato.ferramentas import _contratos

RAIZ_REPO = Path(__file__).resolve().parent.parent
ORACULO = RAIZ_REPO / "casos" / "oraculo-agente1-final.json"
CONFERENCIA = Path(__file__).resolve().parent / "conferencia_final.json"
TAG = "linha-de-base-2"


def arquivo_do_teste(raiz: Path, classe: str) -> Path:
    return next(raiz.glob(f"src/test/**/{classe}.java"))


def corpo_do_metodo(texto: str, metodo: str) -> tuple[int, int]:
    """Início e fim do método no texto (até a anotação do próximo método)."""
    inicio = texto.index(f"void {metodo}(")
    proximo = re.search(r"\n        @", texto[inicio:])
    return inicio, inicio + proximo.start() if proximo else len(texto)


def suite_inteira(raiz: Path) -> set[str]:
    """Roda a suíte toda e devolve os `Classe.metodo` que falharam (só para informar)."""
    pasta = raiz / "target" / "surefire-reports"
    execucao.rodar_com_limite([str(raiz / "mvnw"), "-B", "test"], 900, cwd=raiz)
    falhos = set()
    for arq in pasta.glob("TEST-*.xml"):
        for t in ET.parse(arq).getroot().iter("testcase"):
            if t.find("failure") is not None or t.find("error") is not None:
                classe = arq.stem.removeprefix("TEST-").split(".")[-1].split("$")[0]  # o classname traz o @DisplayName
                falhos.add(f"{classe}.{t.get('name').split('(')[0].split('[')[0].strip()}")
    return falhos


def _tupla(x) -> tuple:
    return tuple(list(x) + [None] * (4 - len(x)))


def conferir_caso(item: dict, esperado: dict, api: Path, trabalho: Path) -> dict:
    """Devolve o resultado de a a e (True, False ou None quando não se aplica) e as anotações."""
    r = dict(id_caso=item["id_caso"], a=False, b=None, c=None, d=None, e=None, outros=[], notas=[])
    classe, metodo = item["teste_afetado"].split(".")
    legitimo = item["rotulo_oraculo"] == "legitima"
    copia = execucao.preparar_copia(api, TAG, trabalho / item["id_caso"])
    try:
        execucao.aplicar_patch(copia, RAIZ_REPO / item["patch"])
        r["a"] = True
    except execucao.ErroDeExecucao as erro:
        r["notas"].append(f"patch não aplica: {erro}")
        return r
    arquivo = arquivo_do_teste(copia, classe)
    # b. o teste afetado falha, e a falha não é de compilação
    res = execucao.rodar_teste(copia, classe, metodo)
    r["b"] = res.compilou and not res.passou
    if not res.compilou:
        r["notas"].append("não compilou depois do patch")
    r["outros"] = sorted(suite_inteira(copia) - {item["teste_afetado"]})
    # e. a diferença de contrato, na categoria pretendida (D122)
    antigo, novo = _contratos(copia)
    mudancas = c.diferenca(antigo, novo)
    obtido = {(m.tipo, m.lado, m.caminho, m.novo_caminho) for m in mudancas}
    previsto = {_tupla(x) for x in esperado["contrato_esperado"]}
    r["e"] = obtido == previsto
    if legitimo:
        r["e"] = r["e"] and all(m.tipo == item["categoria"] and m.lado == item["lado"] for m in mudancas)
    if not r["e"]:
        r["notas"].append(f"diferença obtida {sorted(obtido, key=str)}")
    antes = arquivo.read_bytes().decode("utf-8")
    if legitimo:
        # c. a correção esperada aplica, o teste passa e o guarda aceita
        try:
            execucao.aplicar_patch(copia, RAIZ_REPO / item["correcao_esperada"])
            depois = arquivo.read_bytes().decode("utf-8")
            passou = execucao.rodar_teste(copia, classe, metodo).passou
            veredito = guarda.avaliar(antes, depois, metodo, mudancas, c.rotas_do_contrato(novo))
            r["c"] = passou and veredito.aceito
            if not passou:
                r["notas"].append("a correção esperada não faz o teste passar")
            if not veredito.aceito:
                r["notas"].append("guarda recusa: " + "; ".join(veredito.motivos))
        except execucao.ErroDeExecucao as erro:
            r["c"] = False
            r["notas"].append(f"correção esperada não aplica: {erro}")
    else:
        # d. diferença não vazia (D76); as duas partes atingem o mesmo teste (D93)
        i, j = corpo_do_metodo(antes, metodo)
        trecho = antes[i:j]
        campo = esperado["campo_nao_registrado"]
        ultimo = campo.split(".")[-1]
        atinge_n = f'"{ultimo}"' in trecho or f'.{ultimo}"' in trecho or f'.{ultimo}[' in trecho
        fora_do_contrato = all(campo not in (m.caminho, m.novo_caminho) for m in mudancas)
        corrigido, atinge_l = antes, True
        for _, velho, novo_txt in esperado["legit_no_teste"]:
            i, j = corpo_do_metodo(corrigido, metodo)
            atinge_l = atinge_l and corrigido[i:j].count(velho) == 1
            corrigido = corrigido[:i] + corrigido[i:j].replace(velho, novo_txt) + corrigido[j:]
        arquivo.write_bytes(corrigido.encode("utf-8"))
        ainda_falha = not execucao.rodar_teste(copia, classe, metodo).passou
        r["d"] = bool(mudancas) and atinge_n and atinge_l and fora_do_contrato and ainda_falha
        if not r["d"]:
            r["notas"].append(f"d: diferença={bool(mudancas)} atinge N={atinge_n} atinge parte legítima={atinge_l} "
                              f"N fora do contrato={fora_do_contrato} continua falhando={ainda_falha}")
        if item["correcao_esperada"] is not None:
            r["d"] = False
            r["notas"].append("regressão com correção esperada")
    return r


def conferir_oraculo(oraculo: dict, conferencia: dict) -> list[str]:
    """Erros do oráculo em si: arquivos, rótulos e a composição 16 legítimos + 8 regressões (D91)."""
    erros, casos = [], oraculo["casos"]
    if oraculo.get("versao_api") != TAG:
        erros.append("versao_api diferente da tag")
    if len(casos) != 24 or sum(x["rotulo_oraculo"] == "legitima" for x in casos) != 16:
        erros.append("composição diferente de 24 casos, 16 legítimos e 8 regressões")
    if len({x["teste_afetado"] for x in casos}) != len(casos):
        erros.append("dois casos com o mesmo teste afetado")
    for x in casos:
        if not (RAIZ_REPO / x["patch"]).is_file():
            erros.append(f"{x['id_caso']}: falta o patch")
        legit = x["rotulo_oraculo"] == "legitima"
        if legit != (x["correcao_esperada"] is not None) or (legit and not (RAIZ_REPO / x["correcao_esperada"]).is_file()):
            erros.append(f"{x['id_caso']}: rótulo e correção esperada não combinam")
        if x["id_caso"] not in conferencia:
            erros.append(f"{x['id_caso']}: sem entrada em conferencia_final.json")
    return erros


def tabela(resultados: list[dict]) -> str:
    def m(v):
        return "—" if v is None else ("OK" if v else "FALHA")
    linhas = ["| caso | a patch aplica | b afetado falha | c correção passa + guarda | d regressão | e categoria | outros testes que quebram (info) |",
              "|---|---|---|---|---|---|---|"]
    for r in resultados:
        outros = ", ".join(r["outros"]) if r["outros"] else "nenhum"
        linhas.append(f"| {r['id_caso']} | {m(r['a'])} | {m(r['b'])} | {m(r['c'])} | {m(r['d'])} | {m(r['e'])} | {outros} |")
    return "\n".join(linhas)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--api", type=Path, required=True, help="repositório da API cobaia")
    p.add_argument("--saida", type=Path, help="pasta para gravar resultado.json e tabela.md (nova)")
    p.add_argument("--casos", nargs="*", help="só estes ids (padrão: todos os do oráculo)")
    p.add_argument("--paralelos", type=int, default=3)
    args = p.parse_args(argv)
    oraculo = json.loads(ORACULO.read_text(encoding="utf-8"))
    conferencia = json.loads(CONFERENCIA.read_text(encoding="utf-8"))
    erros = conferir_oraculo(oraculo, conferencia) if not args.casos else []
    for e in erros:
        print("ORÁCULO:", e)
    itens = [x for x in oraculo["casos"] if not args.casos or x["id_caso"] in args.casos]
    with tempfile.TemporaryDirectory(prefix="conferencia-t48-") as tmp, ThreadPoolExecutor(args.paralelos) as pool:
        resultados = list(pool.map(lambda x: conferir_caso(x, conferencia[x["id_caso"]], args.api.resolve(), Path(tmp)), itens))
    texto = tabela(resultados)
    print(texto)
    for r in resultados:
        for n in r["notas"]:
            print(f"  {r['id_caso']}: {n}")
    if args.saida:
        args.saida.mkdir(parents=True)
        (args.saida / "tabela.md").write_text(texto + "\n", encoding="utf-8")
        (args.saida / "resultado.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    falhou = erros or any(v is False for r in resultados for v in (r["a"], r["b"], r["c"], r["d"], r["e"]))
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
