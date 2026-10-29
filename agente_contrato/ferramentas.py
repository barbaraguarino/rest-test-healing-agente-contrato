"""Ferramentas do agente (T23e, D62): o modelo pede, o código confere o que é permitido e executa.

O LLM decide qual ferramenta pedir e o que preencher; este código decide o que é permitido e o texto
da resposta. Uma recusa vira ErroDeFerramenta e volta ao modelo como erro (D124).
"""
import json
from pathlib import Path, PurePosixPath

from agente_contrato.contrato import carregar, descrever_mudancas, diferenca
from agente_contrato.execucao import _git
from agente_contrato.laco import ErroDeFerramenta

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
