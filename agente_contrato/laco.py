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
