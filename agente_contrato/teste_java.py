"""Localiza o método de teste afetado no arquivo Java, para o reparo trocar só o corpo dele (T23e, D116).

Código determinístico, igual ao da v1: conta as chaves `{` e `}` e pula textos e comentários, onde
uma chave não abre nem fecha nada. Fora do que a suíte da API cobaia usa, falha em vez de adivinhar.
"""


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
