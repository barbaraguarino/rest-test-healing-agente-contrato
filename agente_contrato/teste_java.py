"""Localiza o método de teste afetado no arquivo Java, para o reparo trocar só o corpo dele (T23e, D116).

Código determinístico, igual ao da v1: conta as chaves `{` e `}` e pula textos e comentários, onde
uma chave não abre nem fecha nada. Fora do que a suíte da API cobaia usa, falha em vez de adivinhar.
Também lê as chamadas HTTP e as asserções do método, para o guarda (T23g, D77).
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


def _inicio_da_linha(texto: str, i: int) -> int:
    return texto.rfind("\n", 0, i) + 1


def texto_do_metodo(texto: str, nome: str) -> str:
    """O método inteiro, igual ao da v1: anotações (`@Test`, `@Sql`...), assinatura e corpo.

    É o que o Classifier e o Repair recebem da classe de teste (D117b); sobe da assinatura enquanto
    a linha de cima começa com `@`.
    """
    corpo = localizar_metodo(texto, nome)  # garante uma única ocorrência
    assinatura = re.search(rf"\bvoid\s+{re.escape(nome)}\s*\(", texto)
    inicio = _inicio_da_linha(texto, assinatura.start())
    while inicio > 0:
        anterior = _inicio_da_linha(texto, inicio - 1)
        if not texto[anterior:inicio].lstrip().startswith("@"):
            break
        inicio = anterior
    return texto[inicio:corpo.fim]


# ---------------------------------------------------------------- chamadas e asserções (T23g)
# Igual à v1, sem o corpo JSON da requisição, que só a baseline e o comparador usam (T50, T51).
# Premissa da suíte da API cobaia: cada chamada tem a forma mockMvc.perform(verbo("url") ...).

_STATUS = {"isOk": 200, "isCreated": 201, "isNoContent": 204, "isBadRequest": 400,
           "isNotFound": 404, "isUnprocessableEntity": 422}

_CHAMADA = re.compile(r'mockMvc\s*\.perform\(\s*(get|post|put|patch|delete)\(\s*"([^"]+)"')
_JSONPATH = re.compile(r'jsonPath\("([^"]+)"\)')
_STATUS_ESPERADO = re.compile(r"status\(\)\.(?:is\((\d+)\)|(\w+)\(\))")


@dataclass(frozen=True)
class Assercao:
    expressao: str      # ex.: $.itens[0].subtotal
    ini_expressao: int  # conteúdo entre as aspas
    fim_expressao: int
    ini_linha: int      # a linha inteira da asserção
    fim_linha: int


@dataclass(frozen=True)
class Chamada:
    metodo_http: str
    url: str
    rota: str | None    # rota do contrato (ex.: /carrinhos/{id}/itens); None se não casa com nenhuma
    ini: int
    fim: int
    status_esperado: int | None
    assercoes: tuple[Assercao, ...]


def resolver_rota(metodo_http: str, url: str, rotas: dict[str, set[str]]) -> str | None:
    """Casa a URL do teste (/carrinhos/103/itens) com a rota do contrato (/carrinhos/{id}/itens).

    `rotas` mapeia o método HTTP (maiúsculo) ao conjunto de rotas do contrato.
    """
    for rota in sorted(rotas.get(metodo_http.upper(), ())):
        if re.fullmatch(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(rota)), url):
            return rota
    return None


def _status(trecho: str) -> int | None:
    m = _STATUS_ESPERADO.search(trecho)
    if m is None:
        return None
    return int(m.group(1)) if m.group(1) else _STATUS.get(m.group(2))


def analisar_chamadas(texto: str, metodo: Metodo, rotas: dict[str, set[str]]) -> list[Chamada]:
    """As chamadas HTTP do método, cada uma com o status esperado e as asserções `jsonPath` que vêm depois dela."""
    corpo_metodo = texto[metodo.inicio:metodo.fim]
    inicios = [metodo.inicio + m.start() for m in _CHAMADA.finditer(corpo_metodo)]
    limites = inicios[1:] + [metodo.fim]
    chamadas = []
    for ini, fim in zip(inicios, limites):
        trecho = texto[ini:fim]
        m = _CHAMADA.match(trecho)
        assercoes = []
        for a in _JSONPATH.finditer(trecho):
            ini_linha = texto.rfind("\n", 0, ini + a.start()) + 1
            fim_linha = texto.find("\n", ini + a.end())
            assercoes.append(Assercao(a.group(1), ini + a.start(1), ini + a.end(1),
                                      ini_linha, fim_linha + 1))
        chamadas.append(Chamada(m.group(1).upper(), m.group(2),
                                resolver_rota(m.group(1), m.group(2), rotas),
                                ini, fim, _status(trecho), tuple(assercoes)))
    return chamadas


def caminho_da_expressao(expressao: str) -> str:
    """'$.itens[0].subtotal' -> 'itens[].subtotal'; '$[*].sku' -> '[].sku'."""
    sem_indices = re.sub(r"\[(?:\d+|\*)\]", "[]", expressao.removeprefix("$"))
    return sem_indices.removeprefix(".")


def expressao_atinge(expressao: str, caminho: str) -> bool:
    """A asserção trata do campo `caminho` ou de algo dentro dele."""
    cam = caminho_da_expressao(expressao)
    return cam == caminho or cam.startswith(caminho + ".") or cam.startswith(caminho + "[]")
