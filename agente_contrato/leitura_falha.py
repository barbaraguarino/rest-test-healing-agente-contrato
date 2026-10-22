"""Leitura da mensagem de falha do teste afetado, a partir do relatório do Surefire (D100-b).

`execucao.rodar_teste` devolve só `compilou`, `passou` e as durações. O Classifier precisa
saber *como* o teste falhou (ex.: `No value at JSON path "$.descricao"`), então esta
leitura é feita aqui, depois da execução, sem alterar `execucao.py` (D103).
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

LIMITE_MENSAGEM = 1500  # caracteres; a mensagem do Surefire costuma ter menos de 200
_MARCA_CORTE = " [...]"


@dataclass(frozen=True)
class Falha:
    tipo: str      # "failure" (asserção falhou) ou "error" (exceção inesperada)
    excecao: str   # classe da exceção, ex.: java.lang.AssertionError
    mensagem: str  # truncada em LIMITE_MENSAGEM, sem stack trace


def _truncar(texto: str, limite: int) -> str:
    texto = texto.strip()
    if len(texto) <= limite:
        return texto
    return texto[:limite - len(_MARCA_CORTE)].rstrip() + _MARCA_CORTE


def _primeira_linha(texto: str | None) -> str:
    """Quando o atributo `message` falta (ex.: NullPointerException sem texto), a primeira
    linha do corpo do elemento é `Classe: mensagem`; as seguintes são o stack trace."""
    linhas = (texto or "").strip().splitlines()
    return linhas[0] if linhas else ""


def ler_falha(raiz: Path, limite: int = LIMITE_MENSAGEM) -> Falha | None:
    """Devolve a primeira falha ou erro do relatório em `raiz/target/surefire-reports`.

    Devolve None se não há relatório (o teste não compilou) ou se nenhum teste falhou.
    Só vale logo depois de `rodar_teste`, que apaga o relatório anterior antes de rodar.
    """
    pasta = raiz / "target" / "surefire-reports"
    for arquivo in sorted(pasta.glob("TEST-*.xml")):
        for caso in ET.parse(arquivo).getroot().iter("testcase"):
            for elemento in caso:
                if elemento.tag in ("failure", "error"):
                    mensagem = elemento.get("message") or _primeira_linha(elemento.text)
                    return Falha(elemento.tag, elemento.get("type", ""), _truncar(mensagem, limite))
    return None
