"""Prompts versionados do Agente 1 (D70) e o commit em que estavam (D105).

Os textos ficam em `prompts/*.md`, no repositório, para o pacote de replicação mostrar
exatamente o que o modelo recebeu. Os resultados da T10 só valem com os prompts
congelados num commit, registrado em cada execução.
"""

import subprocess
from pathlib import Path

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "prompts"
SUFIXO_ALTERADO = "+alterado"


def carregar(nome: str, pasta: Path = PASTA_PADRAO) -> str:
    """Texto do prompt `pasta/<nome>.md`; falha se o arquivo faltar ou estiver vazio."""
    texto = (pasta / f"{nome}.md").read_text(encoding="utf-8").strip()
    if not texto:
        raise ValueError(f"prompt {nome} está vazio")
    return texto


def commit_dos_prompts(pasta: Path = PASTA_PADRAO) -> str:
    """Hash do último commit que mexeu na pasta de prompts.

    Termina em `+alterado` quando há mudança não commitada ou arquivo novo na pasta: o
    resultado dessa execução não vale para a T10. Sem nenhum commit ainda, devolve
    `sem-commit` (com o sufixo, se for o caso).
    """
    def git(*args: str) -> str:
        proc = subprocess.run(["git", *args, "--", str(pasta)], cwd=pasta, capture_output=True, text=True)
        if proc.returncode != 0 and "does not have any commits" in proc.stderr:
            return ""  # repositório novo: ainda não há commit de prompt
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]}: {proc.stderr.strip()}")
        return proc.stdout.strip()

    commit = git("log", "-1", "--format=%H") or "sem-commit"
    return commit + (SUFIXO_ALTERADO if git("status", "--porcelain") else "")
