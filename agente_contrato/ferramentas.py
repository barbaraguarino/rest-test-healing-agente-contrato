"""Ferramentas do agente (T23e, D62): o modelo pede, o código confere o que é permitido e executa.

O LLM decide qual ferramenta pedir e o que preencher; este código decide o que é permitido e o texto
da resposta. Uma recusa vira ErroDeFerramenta e volta ao modelo como erro (D124).
"""
from pathlib import Path, PurePosixPath

from agente_contrato.laco import ErroDeFerramenta

LIMITE_LEITURA = 30_000  # caracteres; o maior arquivo permitido da API cobaia tem cerca de 26 mil
ARQUIVOS_DE_DOCS = ("docs/openapi.json", "docs/regras-de-negocio.md")  # D73
PERMITIDOS = "`src/`, `docs/openapi.json` e `docs/regras-de-negocio.md`"


def ler_arquivo(raiz: Path, caminho: str) -> str:
    """Lê um arquivo da cópia da API, com o caminho relativo à raiz, se a D73 permitir."""
    relativo = PurePosixPath(caminho)
    dentro_da_d73 = relativo.parts[:1] == ("src",) or str(relativo) in ARQUIVOS_DE_DOCS
    if relativo.is_absolute() or ".." in relativo.parts or not dentro_da_d73:
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    arquivo = (raiz / relativo).resolve()
    if not arquivo.is_relative_to(raiz.resolve()):  # um link que aponta para fora da cópia
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    if not arquivo.is_file():
        raise ErroDeFerramenta(f"Arquivo não encontrado: {caminho}")
    texto = arquivo.read_text(encoding="utf-8")
    if len(texto) > LIMITE_LEITURA:
        return texto[:LIMITE_LEITURA] + f"\n[arquivo cortado: {LIMITE_LEITURA} de {len(texto)} caracteres]"
    return texto
