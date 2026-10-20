"""Leitura de um método de teste JUnit/MockMvc: chamadas HTTP, corpos JSON e asserções.

Código determinístico, só leitura. Todos os deslocamentos (inicio, fim) são
posições no texto completo do arquivo, para que as edições da baseline possam
ser feitas por posição sem reformatar o resto do arquivo.

Premissas, que valem para a suíte da API cobaia (linha-de-base-2): o corpo da
requisição é um text block (\"\"\") com JSON, e cada chamada tem a forma
mockMvc.perform(verbo("url") ...). Fora disso o analisador falha em vez de adivinhar.
"""

import re
from dataclasses import dataclass


class ErroDeAnalise(ValueError):
    pass


# ---------------------------------------------------------------- Java

def _depois_do_literal(texto: str, i: int) -> int:
    """Se em `i` começa um literal ou comentário Java, devolve o índice depois dele."""
    if texto.startswith('"""', i):
        fim = texto.find('"""', i + 3)
        if fim < 0:
            raise ErroDeAnalise("text block sem fechamento")
        return fim + 3
    if texto[i] in "\"'":
        j = i + 1
        while j < len(texto) and texto[j] != texto[i]:
            j += 2 if texto[j] == "\\" else 1
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
    achados = list(re.finditer(rf"\bvoid\s+{re.escape(nome)}\s*\(", texto))
    if len(achados) != 1:
        raise ErroDeAnalise(f"método {nome}: {len(achados)} ocorrências, esperada 1")
    i = texto.find("{", achados[0].end())
    if i < 0:
        raise ErroDeAnalise(f"método {nome} sem corpo")
    inicio, nivel = i, 0
    while i < len(texto):
        proximo = _depois_do_literal(texto, i)
        if proximo != i:
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


# ---------------------------------------------------------------- JSON do corpo

@dataclass(frozen=True)
class Membro:
    chave: str
    ini: int          # início da chave (com aspas)
    fim: int          # fim do valor
    valor: "No"


@dataclass(frozen=True)
class No:
    tipo: str                           # "objeto", "array" ou "valor"
    ini: int
    fim: int
    membros: tuple[Membro, ...] = ()    # objeto
    elementos: tuple["No", ...] = ()    # array


class _LeitorJson:
    def __init__(self, texto: str):
        self.t = texto

    def _espaco(self, i: int) -> int:
        while i < len(self.t) and self.t[i].isspace():
            i += 1
        return i

    def _string(self, i: int) -> int:
        j = i + 1
        while j < len(self.t) and self.t[j] != '"':
            j += 2 if self.t[j] == "\\" else 1
        if j >= len(self.t):
            raise ErroDeAnalise("string JSON sem fechamento")
        return j + 1

    def valor(self, i: int) -> No:
        i = self._espaco(i)
        c = self.t[i] if i < len(self.t) else ""
        if c == "{":
            return self._objeto(i)
        if c == "[":
            return self._array(i)
        if c == '"':
            return No("valor", i, self._string(i))
        j = i
        while j < len(self.t) and self.t[j] not in ",}]" and not self.t[j].isspace():
            j += 1
        if j == i:
            raise ErroDeAnalise(f"JSON inválido na posição {i}")
        return No("valor", i, j)

    def _objeto(self, i: int) -> No:
        membros, j = [], self._espaco(i + 1)
        while self.t[j] != "}":
            if self.t[j] != '"':
                raise ErroDeAnalise(f"chave JSON esperada na posição {j}")
            fim_chave = self._string(j)
            dois_pontos = self._espaco(fim_chave)
            if self.t[dois_pontos] != ":":
                raise ErroDeAnalise(f"':' esperado na posição {dois_pontos}")
            valor = self.valor(dois_pontos + 1)
            membros.append(Membro(self.t[j + 1:fim_chave - 1], j, valor.fim, valor))
            j = self._espaco(valor.fim)
            if self.t[j] == ",":
                j = self._espaco(j + 1)
        return No("objeto", i, j + 1, membros=tuple(membros))

    def _array(self, i: int) -> No:
        elementos, j = [], self._espaco(i + 1)
        while self.t[j] != "]":
            elemento = self.valor(j)
            elementos.append(elemento)
            j = self._espaco(elemento.fim)
            if self.t[j] == ",":
                j = self._espaco(j + 1)
        return No("array", i, j + 1, elementos=tuple(elementos))


def analisar_json(texto: str, inicio: int) -> No:
    """Lê o JSON que começa em `inicio` (espaços antes são aceitos)."""
    try:
        return _LeitorJson(texto).valor(inicio)
    except IndexError:
        raise ErroDeAnalise("JSON terminou antes do esperado") from None


def _partes(caminho: str) -> list[str]:
    """'itens[].produtoId' -> ['itens', '[]', 'produtoId']"""
    return [p for p in re.findall(r"\[\]|[^.\[\]]+", caminho)]


def _descer(nos: list[No], parte: str) -> list[No]:
    if parte == "[]":
        return [e for n in nos if n.tipo == "array" for e in n.elementos]
    return [m.valor for n in nos if n.tipo == "objeto" for m in n.membros if m.chave == parte]


def localizar_membros(raiz: No, caminho: str) -> list[Membro]:
    """Membros do JSON que o caminho designa (vários, se passar por um array)."""
    partes = _partes(caminho)
    if not partes or partes[-1] == "[]":
        return []
    pais = [raiz]
    for parte in partes[:-1]:
        pais = _descer(pais, parte)
    return [m for n in pais if n.tipo == "objeto" for m in n.membros if m.chave == partes[-1]]


def localizar_objetos(raiz: No, caminho: str) -> list[No]:
    """Objetos que o caminho designa; '' é a raiz. Serve para inserir campos."""
    nos = [raiz]
    for parte in _partes(caminho):
        nos = _descer(nos, parte)
    return [n for n in nos if n.tipo == "objeto"]


# ---------------------------------------------------------------- chamadas e asserções

_STATUS = {"isOk": 200, "isCreated": 201, "isNoContent": 204, "isBadRequest": 400,
           "isNotFound": 404, "isUnprocessableEntity": 422}

_CHAMADA = re.compile(r'mockMvc\s*\.perform\(\s*(get|post|put|patch|delete)\(\s*"([^"]+)"')
_CORPO = re.compile(r'\.content\(\s*"""')
_JSONPATH = re.compile(r'jsonPath\("([^"]+)"\)')
_STATUS_ESPERADO = re.compile(r"status\(\)\.(?:is\((\d+)\)|(\w+)\(\))")


@dataclass(frozen=True)
class Assercao:
    expressao: str
    ini_expressao: int  # conteúdo entre as aspas
    fim_expressao: int
    ini_linha: int      # a linha inteira da asserção, para remoção
    fim_linha: int


@dataclass(frozen=True)
class Chamada:
    metodo_http: str
    url: str
    rota: str | None            # rota do contrato (ex.: /carrinhos/{id}/itens)
    ini: int
    fim: int
    status_esperado: int | None
    corpo: No | None
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
    corpo_metodo = texto[metodo.inicio:metodo.fim]
    inicios = [metodo.inicio + m.start() for m in _CHAMADA.finditer(corpo_metodo)]
    limites = inicios[1:] + [metodo.fim]
    chamadas = []
    for ini, fim in zip(inicios, limites):
        trecho = texto[ini:fim]
        m = _CHAMADA.match(trecho)
        corpo = None
        achado = _CORPO.search(trecho)
        if achado is not None:
            corpo = analisar_json(texto, ini + achado.end())
        assercoes = []
        for a in _JSONPATH.finditer(trecho):
            ini_linha = texto.rfind("\n", 0, ini + a.start()) + 1
            fim_linha = texto.find("\n", ini + a.end())
            assercoes.append(Assercao(a.group(1), ini + a.start(1), ini + a.end(1),
                                      ini_linha, fim_linha + 1))
        chamadas.append(Chamada(m.group(1).upper(), m.group(2),
                                resolver_rota(m.group(1), m.group(2), rotas),
                                ini, fim, _status(trecho), corpo, tuple(assercoes)))
    return chamadas


def caminho_da_expressao(expressao: str) -> str:
    """'$.itens[0].subtotal' -> 'itens[].subtotal'; '$[*].sku' -> '[].sku'."""
    sem_indices = re.sub(r"\[(?:\d+|\*)\]", "[]", expressao.removeprefix("$"))
    return sem_indices.removeprefix(".")


def expressao_atinge(expressao: str, caminho: str) -> bool:
    """A asserção trata do campo `caminho` ou de algo dentro dele."""
    cam = caminho_da_expressao(expressao)
    return cam == caminho or cam.startswith(caminho + ".") or cam.startswith(caminho + "[]")
