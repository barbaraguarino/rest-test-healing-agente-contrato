"""Localiza o método de teste afetado no arquivo Java, para o reparo trocar só o corpo dele (T23e, D116).

Código determinístico, igual ao da v1: conta as chaves `{` e `}` e pula textos e comentários, onde
uma chave não abre nem fecha nada. Fora do que a suíte da API cobaia usa, falha em vez de adivinhar.
"""
import re
from dataclasses import dataclass


class ErroDeAnalise(ValueError):
    pass


def _depois_do_literal(texto: str, i: int) -> int:
    """Se em `i` começa um texto, caractere ou comentário Java, devolve o índice logo depois dele; senão, `i`."""
    if texto.startswith('"""', i):  # text block; um \""" escapado dentro dele não é tratado
        fim = texto.find('"""', i + 3)
        if fim < 0:
            raise ErroDeAnalise("text block sem fechamento")
        return fim + 3
    if texto[i] in "\"'":
        j = i + 1
        while j < len(texto) and texto[j] != texto[i]:
            j += 2 if texto[j] == "\\" else 1  # \" não fecha o texto: pula a barra e o que vem depois
        return j + 1
    if texto.startswith("//", i):
        fim = texto.find("\n", i)
        return len(texto) if fim < 0 else fim
    if texto.startswith("/*", i):
        fim = texto.find("*/", i + 2)
        if fim < 0:
            raise ErroDeAnalise("comentário sem fechamento")
        return fim + 2
    return i


@dataclass(frozen=True)
class Metodo:
    nome: str
    inicio: int  # posição do '{' do corpo
    fim: int     # posição logo depois do '}' do corpo


def localizar_metodo(texto: str, nome: str) -> Metodo:
    """O corpo do método `void nome(...)`, que deve aparecer exatamente uma vez no texto."""
    achados = list(re.finditer(rf"\bvoid\s+{re.escape(nome)}\s*\(", texto))
    if len(achados) != 1:
        raise ErroDeAnalise(f"método {nome}: {len(achados)} ocorrências, esperada 1")
    i = texto.find("{", achados[0].end())
    if i < 0:
        raise ErroDeAnalise(f"método {nome} sem corpo")
    inicio, nivel = i, 0
    while i < len(texto):
        proximo = _depois_do_literal(texto, i)
        if proximo != i:  # uma chave dentro de texto ou comentário não conta
            i = proximo
            continue
        if texto[i] == "{":
            nivel += 1
        elif texto[i] == "}":
            nivel -= 1
            if nivel == 0:
                return Metodo(nome, inicio, i + 1)
        i += 1
    raise ErroDeAnalise(f"método {nome} sem fechamento")
