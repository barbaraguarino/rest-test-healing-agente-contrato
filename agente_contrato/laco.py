"""Núcleo do laço do agente (T23c, D62): pedir ao modelo, executar a ferramenta pedida e repetir.

O LLM decide qual ferramenta pedir e quando parar; este código executa, conta as chamadas e
aplica os limites. Os tipos imitam os blocos `tool_use` e `tool_result` da API do Claude, para a
T23i só traduzir de um para o outro.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PedidoFerramenta:
    """O modelo pede uma ferramenta (bloco `tool_use`); `id` liga o pedido à resposta."""
    id: str
    nome: str
    entrada: dict


@dataclass(frozen=True)
class RespostaModelo:
    """Uma resposta do modelo: texto e, se ele não terminou, os pedidos de ferramenta."""
    texto: str
    pedidos: tuple[PedidoFerramenta, ...] = ()

    @property
    def terminou(self) -> bool:
        return not self.pedidos  # na API, `stop_reason` "end_turn" em vez de "tool_use"


@dataclass(frozen=True)
class ResultadoFerramenta:
    """O que o código devolve ao modelo (bloco `tool_result`); `erro` vira `is_error`."""
    id_pedido: str
    conteudo: str
    erro: bool = False


@dataclass(frozen=True)
class ResultadoLaco:
    texto_final: str | None  # None quando o laço parou pelo limite, sem o modelo terminar
    chamadas: int
    motivo: str  # "terminou" ou "limite_de_chamadas"
    historico: list


def executar_pedido(pedido: PedidoFerramenta, ferramentas: dict) -> ResultadoFerramenta:
    """Executa um pedido; um nome que não existe volta ao modelo como erro, e o laço segue."""
    ferramenta = ferramentas.get(pedido.nome)
    if ferramenta is None:
        disponiveis = ", ".join(sorted(ferramentas))
        return ResultadoFerramenta(
            pedido.id, f"Ferramenta desconhecida: {pedido.nome}. Disponíveis: {disponiveis}", erro=True)
    return ResultadoFerramenta(pedido.id, ferramenta(pedido.entrada))


def rodar_laco(modelo, mensagem_inicial: str, ferramentas: dict, max_chamadas: int) -> ResultadoLaco:
    """Pergunta ao modelo, executa o que ele pedir e repete até ele terminar ou o limite chegar.

    `modelo` recebe o histórico e devolve uma RespostaModelo; `ferramentas` liga cada nome a uma
    função que recebe a entrada do pedido e devolve um texto.
    """
    historico = [mensagem_inicial]
    for chamada in range(1, max_chamadas + 1):
        resposta = modelo(historico)
        historico.append(resposta)
        if resposta.terminou:
            return ResultadoLaco(resposta.texto, chamada, "terminou", historico)
        resultados = tuple(executar_pedido(p, ferramentas) for p in resposta.pedidos)
        historico.append(resultados)
    return ResultadoLaco(None, max_chamadas, "limite_de_chamadas", historico)
