"""Ferramentas do agente (T23e, D62): o modelo pede, o código confere o que é permitido e executa.

O LLM decide qual ferramenta pedir e o que preencher; este código decide o que é permitido e o texto
da resposta. Uma recusa vira ErroDeFerramenta e volta ao modelo como erro (D124).
"""
import json
from pathlib import Path, PurePosixPath

from agente_contrato.contrato import carregar, descrever_mudancas, diferenca
from agente_contrato.execucao import LIMITE_TESTE_S, ErroDeExecucao, _git, ler_falha
from agente_contrato.laco import ErroDeFerramenta
from agente_contrato.relogio import RelogioCaso

LIMITE_LEITURA = 30_000  # caracteres; o maior arquivo permitido da API cobaia tem cerca de 26 mil
CONTRATO = "docs/openapi.json"
ARQUIVOS_DE_DOCS = (CONTRATO, "docs/regras-de-negocio.md")  # D73
PERMITIDOS = "`src/`, `docs/openapi.json` e `docs/regras-de-negocio.md`"


def ler_arquivo(raiz: Path, caminho: str) -> str:
    """Lê um arquivo da cópia da API, com o caminho relativo à raiz, se a D73 permitir.

    Numa pasta, devolve a lista dos arquivos dela e das subpastas, com os caminhos prontos para pedir.
    """
    relativo = PurePosixPath(caminho)
    dentro_da_d73 = relativo.parts[:1] == ("src",) or str(relativo) in ARQUIVOS_DE_DOCS
    if relativo.is_absolute() or ".." in relativo.parts or not dentro_da_d73:
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    arquivo = (raiz / relativo).resolve()
    if not arquivo.is_relative_to(raiz.resolve()):  # um link que aponta para fora da cópia
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    if arquivo.is_dir():
        return _listar(raiz.resolve(), arquivo, str(relativo))
    if not arquivo.is_file():
        raise ErroDeFerramenta(f"Arquivo não encontrado: {caminho}")
    texto = arquivo.read_text(encoding="utf-8")
    if len(texto) > LIMITE_LEITURA:
        return texto[:LIMITE_LEITURA] + f"\n[arquivo cortado: {LIMITE_LEITURA} de {len(texto)} caracteres]"
    return texto


def _listar(raiz: Path, pasta: Path, nome: str) -> str:
    """Os arquivos da pasta, em ordem; um atalho que aponta para fora da cópia não aparece."""
    arquivos = sorted(a.relative_to(raiz).as_posix() for a in pasta.rglob("*")
                      if a.is_file() and a.resolve().is_relative_to(raiz))
    if not arquivos:
        return f"A pasta {nome} não tem arquivos."
    return "\n".join([f"Arquivos em {nome}:"] + [f"- {a}" for a in arquivos])


def ver_diferenca(raiz: Path) -> str:
    """A evidência do Agente 1 (D62, D122): o contrato da tag comparado com o contrato depois do patch.

    A cópia é um clone na tag e o patch só muda os arquivos, então o antigo é o do HEAD. Uma falha
    do git não é culpa do modelo: vira ErroDeExecucao e para o caso (D124).
    """
    antigo = json.loads(_git("show", f"HEAD:{CONTRATO}", cwd=raiz))
    return descrever_mudancas(diferenca(antigo, carregar(raiz / CONTRATO)))


def rodar_teste(rodar, raiz: Path, classe: str, metodo: str, relogio: RelogioCaso) -> str:
    """Roda sempre o teste afetado (D112), com o menor entre 120 s e o que resta do caso (D111a, D118).

    `rodar` é o `execucao.rodar_teste`, injetável nos testes. O estouro de tempo volta ao modelo como
    erro e o laço segue; uma falha de infraestrutura (ErroDeExecucao) não é culpa dele e para o caso (D124).
    """
    limite_s = relogio.limite_para_teste(LIMITE_TESTE_S)
    try:
        resultado = rodar(raiz, classe, metodo, limite_s)
    except ErroDeExecucao as exc:
        if exc.codigo != "timeout":
            raise
        raise ErroDeFerramenta(f"O teste passou de {limite_s:g} s e foi interrompido.") from None
    if not resultado.compilou:
        return "O teste não compilou."
    if resultado.passou:
        return "O teste passou."
    falha = ler_falha(raiz / "target" / "surefire-reports")
    if falha is None:  # ex.: o teste foi ignorado (@Disabled)
        return "O teste não passou, e o relatório não traz mensagem de falha."
    return f"O teste falhou.\n{falha.tipo} {falha.excecao}: {falha.mensagem}"
