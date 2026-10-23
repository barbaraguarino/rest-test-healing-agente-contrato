"""Baseline determinística do Agente 1 (D75), sem LLM.

Lê a lista de mudanças do contrato (contrato.py) e aplica cada uma
mecanicamente no método de teste afetado (teste_java.py). Se nenhuma mudança
atinge o teste, não repara. No T09 o LLM passa a decidir o que a baseline
decide por regra: se a mudança é legítima e como o teste deve ser editado.

Convenções da suíte da API cobaia que as regras assumem: inteiros são
conferidos com is(N), decimais com decimal("N") e o resto com literais.
Uma mudança que atinge o teste mas que nenhuma regra sabe aplicar (por exemplo,
conversão de tipo sem regra) fica em `ignoradas` com o motivo, e o teste segue
quebrado: é uma limitação da baseline, e não do método.
"""

import re
from dataclasses import dataclass

from . import contrato as c
from . import teste_java as tj

REPARAR = "reparar"
NAO_REPARAR = "nao_reparar"

VALOR_PADRAO_STRING = '"texto"'


@dataclass(frozen=True)
class Resultado:
    decisao: str
    texto: str  # arquivo inteiro; igual ao original em nao_reparar
    aplicadas: tuple[c.Mudanca, ...]
    ignoradas: tuple[tuple[c.Mudanca, str], ...]


@dataclass(frozen=True)
class Edicao:
    ini: int
    fim: int
    novo: str
    remove_linha: bool = False


# ---------------------------------------------------------------- valores

_NUMERO = re.compile(r"-?\d+(\.\d+)?")


def valor_padrao(p: c.Propriedade) -> str | None:
    """Valor JSON padrão por tipo, para o campo obrigatório novo."""
    if p.enum:
        return f'"{p.enum[0]}"'
    return {"string": VALOR_PADRAO_STRING, "integer": "1", "number": "1.0",
            "boolean": "true", "array": "[]", "object": "{}"}.get(p.tipo)


def converter(literal: str, antes: c.Propriedade, depois: c.Propriedade) -> str | None:
    """Converte um literal JSON para o tipo novo; None se não há regra."""
    if depois.tipo == "string":
        if antes.tipo == "boolean" and depois.enum and len(depois.enum) >= 2:
            return f'"{depois.enum[0] if literal == "true" else depois.enum[1]}"'
        if antes.tipo in ("integer", "number", "boolean") and not depois.enum:
            return f'"{literal}"'
    elif depois.tipo in ("integer", "number") and antes.tipo == "string":
        interno = literal.strip('"')
        return interno if _NUMERO.fullmatch(interno) else None
    elif depois.tipo == "boolean" and antes.tipo == "string":
        interno = literal.strip('"')
        return interno if interno in ("true", "false") else None
    elif depois.tipo == "number" and antes.tipo == "integer":
        return literal
    elif depois.tipo == "integer" and antes.tipo == "number":
        return literal.split(".")[0] if re.fullmatch(r"-?\d+(\.0+)?", literal) else None
    return None


def _literal_da_asserção(arg: str) -> str | None:
    arg = arg.strip()
    for padrao in (r"is\((.+)\)", r'decimal\("([^"]+)"\)'):
        m = re.fullmatch(padrao, arg)
        if m:
            arg = m.group(1).strip()
            break
    if re.fullmatch(r'"[^"]*"|true|false|-?\d+(\.\d+)?', arg):
        return arg
    return None


def _arg_da_asserção(tipo: str, literal: str) -> str:
    if tipo == "integer":
        return f"is({literal})"
    if tipo == "number":
        return f'decimal("{literal}")'
    return literal


# ---------------------------------------------------------------- utilidades de caminho

def _pai(caminho: str) -> str:
    return caminho.rsplit(".", 1)[0] if "." in caminho else ""


def _ultimo(caminho: str) -> str:
    return caminho.rsplit(".", 1)[-1]


# ---------------------------------------------------------------- edições na requisição

def _renomear_chave(texto: str, corpo: tj.No, m: c.Mudanca) -> list[Edicao]:
    novo = _ultimo(m.novo_caminho)
    return [Edicao(x.ini, x.ini + len(x.chave) + 2, f'"{novo}"')
            for x in tj.localizar_membros(corpo, m.caminho)]


def _remover_membro(texto: str, corpo: tj.No, m: c.Mudanca) -> list[Edicao]:
    edicoes = []
    for obj in tj.localizar_objetos(corpo, _pai(m.caminho)):
        for i, x in enumerate(obj.membros):
            if x.chave != _ultimo(m.caminho):
                continue
            if i + 1 < len(obj.membros):
                edicoes.append(Edicao(x.ini, obj.membros[i + 1].ini, ""))
            elif i > 0:
                edicoes.append(Edicao(obj.membros[i - 1].fim, x.fim, ""))
            else:
                edicoes.append(Edicao(x.ini, x.fim, ""))
    return edicoes


def _converter_valor(texto: str, corpo: tj.No, m: c.Mudanca) -> list[Edicao]:
    edicoes = []
    for x in tj.localizar_membros(corpo, m.caminho):
        novo = converter(texto[x.valor.ini:x.valor.fim], m.antes, m.depois)
        if novo is not None:
            edicoes.append(Edicao(x.valor.ini, x.valor.fim, novo))
    return edicoes


def _acrescentar_membro(texto: str, corpo: tj.No, m: c.Mudanca) -> list[Edicao]:
    valor = valor_padrao(m.depois)
    if valor is None:
        return []
    chave = _ultimo(m.caminho)
    edicoes = []
    for obj in tj.localizar_objetos(corpo, _pai(m.caminho)):
        if any(x.chave == chave for x in obj.membros):
            continue
        par = f'"{chave}": {valor}'
        if not obj.membros:
            edicoes.append(Edicao(obj.ini + 1, obj.ini + 1, par))
            continue
        ultimo = obj.membros[-1]
        inicio_linha = texto.rfind("\n", 0, ultimo.ini) + 1
        indentacao = texto[inicio_linha:ultimo.ini]
        if "\n" in texto[obj.ini:ultimo.ini] and not indentacao.strip():
            edicoes.append(Edicao(ultimo.fim, ultimo.fim, f",\n{indentacao}{par}"))
        else:
            edicoes.append(Edicao(ultimo.fim, ultimo.fim, f", {par}"))
    return edicoes


# ---------------------------------------------------------------- edições na resposta

def _renomear_expressao(texto: str, a: tj.Assercao, m: c.Mudanca) -> list[Edicao]:
    padrao = "^" + re.escape("$")
    for parte in re.findall(r"\[\]|[^.\[\]]+", m.caminho):
        padrao += r"\[(?:\d+|\*)\]" if parte == "[]" else r"\.?" + re.escape(parte)
    achado = re.match(padrao, a.expressao)
    if achado is None:
        return []
    antigo = _ultimo(m.caminho)
    ini = a.ini_expressao + achado.end() - len(antigo)
    return [Edicao(ini, ini + len(antigo), _ultimo(m.novo_caminho))]


def _argumento_value(texto: str, a: tj.Assercao) -> tuple[int, int] | None:
    """Posição do argumento de .value(...) logo depois do jsonPath("..."), se for o caso."""
    inicio = a.fim_expressao + 1
    prefixo = ").value("
    if not texto.startswith(prefixo, inicio):
        return None
    ini = inicio + len(prefixo)
    nivel, i = 1, ini
    while i < len(texto):
        if texto[i] == '"':
            i = texto.find('"', i + 1)
        elif texto[i] == "(":
            nivel += 1
        elif texto[i] == ")":
            nivel -= 1
            if nivel == 0:
                return ini, i
        i += 1
    return None


def _linha_unica(texto: str, a: tj.Assercao) -> bool:
    return texto[a.ini_linha:a.fim_linha].count("jsonPath(") == 1


def _remover_assercao(texto: str, a: tj.Assercao) -> list[Edicao]:
    if not _linha_unica(texto, a):
        raise tj.ErroDeAnalise("linha com mais de uma asserção jsonPath")
    return [Edicao(a.ini_linha, a.fim_linha, "", remove_linha=True)]


def _converter_assercao(texto: str, a: tj.Assercao, m: c.Mudanca) -> list[Edicao]:
    pos = _argumento_value(texto, a)
    if pos is None:
        return []
    literal = _literal_da_asserção(texto[pos[0]:pos[1]])
    novo = converter(literal, m.antes, m.depois) if literal is not None else None
    if novo is None:
        return []
    return [Edicao(pos[0], pos[1], _arg_da_asserção(m.depois.tipo, novo))]


# ---------------------------------------------------------------- aplicação das edições

def _aplicar(texto: str, edicoes: list[Edicao]) -> str:
    unicas = sorted(set(edicoes), key=lambda e: (e.ini, e.fim))
    # A última asserção da cadeia carrega o ';'. Se ela sai, o ';' passa para a linha anterior que fica.
    removidas = [e for e in unicas if e.remove_linha]
    extras = []
    for e in removidas:
        if not texto[e.ini:e.fim].rstrip().endswith(";"):
            continue
        pos = e.ini
        for r in sorted(removidas, key=lambda r: -r.ini):
            if r.fim == pos:
                pos = r.ini
        if pos > 0 and texto[pos - 1] == "\n":
            extras.append(Edicao(pos - 1, pos - 1, ";"))
    todas = sorted(unicas + extras, key=lambda e: (e.ini, e.fim))
    for anterior, atual in zip(todas, todas[1:]):
        if atual.ini < anterior.fim:
            raise tj.ErroDeAnalise(f"edições sobrepostas em {anterior.ini}-{anterior.fim}")
    for e in reversed(todas):
        texto = texto[:e.ini] + e.novo + texto[e.fim:]
    return texto


# ---------------------------------------------------------------- baseline

def _edicoes_da_mudanca(texto: str, m: c.Mudanca, chamadas: list[tj.Chamada]) -> list[Edicao]:
    edicoes = []
    for ch in chamadas:
        if m.lado == c.REQUISICAO and ch.corpo is not None:
            if m.tipo == c.RENOMEACAO:
                edicoes += _renomear_chave(texto, ch.corpo, m)
            elif m.tipo == c.REMOCAO:
                edicoes += _remover_membro(texto, ch.corpo, m)
            elif m.tipo == c.ALTERACAO_TIPO:
                edicoes += _converter_valor(texto, ch.corpo, m)
            elif m.tipo == c.CAMPO_OBRIGATORIO_NOVO:
                edicoes += _acrescentar_membro(texto, ch.corpo, m)
        elif m.lado == c.RESPOSTA and ch.status_esperado and 200 <= ch.status_esperado < 300:
            for a in ch.assercoes:
                if not tj.expressao_atinge(a.expressao, m.caminho):
                    continue
                if m.tipo == c.RENOMEACAO:
                    edicoes += _renomear_expressao(texto, a, m)
                elif m.tipo == c.REMOCAO:
                    edicoes += _remover_assercao(texto, a)
                elif m.tipo == c.ALTERACAO_TIPO and tj.caminho_da_expressao(a.expressao) == m.caminho:
                    edicoes += _converter_assercao(texto, a, m)
    return edicoes


def reparar(texto: str, nome_metodo: str, mudancas: list[c.Mudanca],
            rotas: dict[str, set[str]]) -> Resultado:
    metodo = tj.localizar_metodo(texto, nome_metodo)
    chamadas = tj.analisar_chamadas(texto, metodo, rotas)
    edicoes: list[Edicao] = []
    aplicadas, ignoradas = [], []
    for m in mudancas:
        alvo = [ch for ch in chamadas if (ch.metodo_http, ch.rota) == (m.metodo, m.rota)]
        if not alvo:
            ignoradas.append((m, "a mudança não atinge o teste"))
            continue
        novas = _edicoes_da_mudanca(texto, m, alvo)
        if novas:
            edicoes += novas
            aplicadas.append(m)
        else:
            ignoradas.append((m, "nenhuma regra se aplica ao que o teste contém"))
    if not edicoes:
        return Resultado(NAO_REPARAR, texto, (), tuple(ignoradas))
    return Resultado(REPARAR, _aplicar(texto, edicoes), tuple(aplicadas), tuple(ignoradas))


rotas_do_contrato = c.rotas_do_contrato  # atalho: a função passou para contrato.py (D103)
