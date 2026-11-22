"""Guarda contra reparos que enfraquecem o teste (T23g; D62, D77, D115, D116).

Código determinístico, sem LLM: compara o arquivo de teste original com o reparado e diz se o reparo
é aceito e, se não for, por quê. Heurística textual sobre o método afetado, com o alcance da suíte da
API cobaia: as asserções são `.andExpect(...)` do MockMvc e `assertThat(...)`.
"""
import re
from dataclasses import dataclass

from agente_contrato import contrato as c
from agente_contrato import teste_java as tj

# Matchers e status que aceitam quase qualquer coisa (D62; lista registrada na D115). Se o reparo
# aumenta o uso de algum deles, a asserção ficou mais fraca.
_FRACOS = ("anything()", "notNullValue()", ".exists()", "isNotEmpty()", "any(",
           "is2xxSuccessful()", "is3xxRedirection()", "is4xxClientError()", "is5xxServerError()")

# Um argumento de `.value(...)` que começa com uma chamada, como `is(3)` ou `Matchers.closeTo(...)`.
_MATCHER = re.compile(r"[A-Za-z_][\w.]*\s*\(")


@dataclass(frozen=True)
class Veredito:
    aceito: bool
    motivos: tuple[str, ...]


def _asserções(trecho: str) -> int:
    return trecho.count(".andExpect(") + trecho.count("assertThat(")


def _sobre_campo_removido(texto: str, metodo: tj.Metodo, mudancas: list[c.Mudanca],
                          rotas: dict[str, set[str]]) -> int:
    """Quantas asserções tratam de um campo que a diferença de contrato removeu (D77)."""
    removidas = [m for m in mudancas if m.tipo == c.REMOCAO and m.lado == c.RESPOSTA]
    total = 0
    for ch in tj.analisar_chamadas(texto, metodo, rotas):
        if not (ch.status_esperado and 200 <= ch.status_esperado < 300):
            continue
        for a in ch.assercoes:
            if any((m.metodo, m.rota) == (ch.metodo_http, ch.rota)
                   and tj.expressao_atinge(a.expressao, m.caminho) for m in removidas):
                total += 1
    return total


def _argumentos_de_value(trecho: str) -> list[str]:
    """O que está entre os parênteses de cada `.value(...)`, pulando textos e comentários."""
    argumentos, i = [], 0
    while i < len(trecho):
        proximo = tj._depois_do_literal(trecho, i)
        if proximo != i:
            i = proximo
            continue
        if not trecho.startswith(".value(", i):
            i += 1
            continue
        inicio = j = i + len(".value(")
        nivel = 1
        while j < len(trecho) and nivel:
            proximo = tj._depois_do_literal(trecho, j)
            if proximo != j:
                j = proximo
                continue
            nivel += {"(": 1, ")": -1}.get(trecho[j], 0)
            j += 1
        argumentos.append(trecho[inicio:j - 1].strip())
        i = j
    return argumentos


def _matchers_e_literais(trecho: str) -> tuple[int, int]:
    """Quantos `.value(...)` usam matcher (`is(3)`) e quantos usam literal (`3`, `"x"`)."""
    argumentos = _argumentos_de_value(trecho)
    matchers = sum(1 for a in argumentos if _MATCHER.match(a))
    return matchers, len(argumentos) - matchers


def avaliar(antes: str, depois: str, nome_metodo: str, mudancas: list[c.Mudanca],
            rotas: dict[str, set[str]]) -> Veredito:
    """Aceita o reparo `depois` do arquivo `antes` só se o teste não ficou mais fraco.

    `antes` é o arquivo original, antes de qualquer reparo; `mudancas` é a diferença de contrato (T23d),
    e `rotas`, as rotas do contrato novo, para a exceção da D77.
    """
    motivos = []
    if depois.count("@Test") < antes.count("@Test"):
        motivos.append("teste removido")
    if depois.count("@Disabled") > antes.count("@Disabled"):
        motivos.append("@Disabled acrescentado")
    try:
        m_antes = tj.localizar_metodo(antes, nome_metodo)
        m_depois = tj.localizar_metodo(depois, nome_metodo)
    except tj.ErroDeAnalise:
        motivos.append("método afetado não encontrado depois do reparo")
        return Veredito(False, tuple(motivos))
    # D116: só o corpo do método afetado pode mudar; anotações, assinatura e o resto do arquivo, não.
    if (antes[:m_antes.inicio] != depois[:m_depois.inicio]
            or antes[m_antes.fim:] != depois[m_depois.fim:]):
        motivos.append("alteração fora do corpo do método afetado")
    t_antes, t_depois = antes[m_antes.inicio:m_antes.fim], depois[m_depois.inicio:m_depois.fim]
    # D77: a exceção vale só para as asserções que saíram de fato; se a do campo removido continua
    # no teste, não há folga para apagar outra.
    saidas = (_sobre_campo_removido(antes, m_antes, mudancas, rotas)
              - _sobre_campo_removido(depois, m_depois, mudancas, rotas))
    minimo = _asserções(t_antes) - max(0, saidas)
    if _asserções(t_depois) < minimo:
        motivos.append(f"menos asserções ({_asserções(t_depois)}) que o permitido ({minimo})")
    if sum(t_depois.count(f) for f in _FRACOS) > sum(t_antes.count(f) for f in _FRACOS):
        motivos.append("matcher afrouxado")
    # D115 (pela D53): um literal em `.value(...)` converte o valor lido e esconde a mudança de tipo.
    matchers_antes, literais_antes = _matchers_e_literais(t_antes)
    matchers_depois, literais_depois = _matchers_e_literais(t_depois)
    if matchers_depois < matchers_antes and literais_depois > literais_antes:
        motivos.append("matcher trocado por literal em .value(...)")
    return Veredito(not motivos, tuple(motivos))
