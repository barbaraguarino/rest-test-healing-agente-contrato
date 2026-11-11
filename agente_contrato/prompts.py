"""Prompts versionados do Agente 1 (D70): os textos ficam em `prompts/*.md`, no repositório.

Assim o pacote de replicação mostra exatamente o que o modelo recebeu. Igual ao `carregar` da v1
(tag `rodada-2`); o registro do commit dos prompts em cada execução (D105) fica para a T23h.
"""
from pathlib import Path

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "prompts"


def carregar(nome: str, pasta: Path = PASTA_PADRAO) -> str:
    """Texto do prompt `pasta/<nome>.md`; falha se o arquivo faltar ou estiver vazio."""
    texto = (pasta / f"{nome}.md").read_text(encoding="utf-8").strip()
    if not texto:
        raise ValueError(f"prompt {nome} está vazio")
    return texto
