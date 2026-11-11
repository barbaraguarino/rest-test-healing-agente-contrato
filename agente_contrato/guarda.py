"""Guarda contra reparos que enfraquecem o teste (T23g; D62, D77, D115, D116).

Código determinístico, sem LLM: compara o arquivo de teste original com o reparado e diz se o reparo
é aceito e, se não for, por quê. Heurística textual sobre o método afetado, com o alcance da suíte da
API cobaia: as asserções são `.andExpect(...)` do MockMvc e `assertThat(...)`.
"""
from dataclasses import dataclass

from agente_contrato import contrato as c
from agente_contrato import teste_java as tj

# Matchers e status que aceitam quase qualquer coisa (D62; lista registrada na D115). Se o reparo
# aumenta o uso de algum deles, a asserção ficou mais fraca.
_FRACOS = ("anything()", "notNullValue()", ".exists()", "isNotEmpty()", "any(",
           "is2xxSuccessful()", "is3xxRedirection()", "is4xxClientError()", "is5xxServerError()")

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
    return Veredito(not motivos, tuple(motivos))
