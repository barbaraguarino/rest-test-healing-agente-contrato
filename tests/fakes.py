"""Cliente de LLM falso: devolve respostas roteirizadas e guarda o que recebeu.

Nenhum teste automatizado chama a API paga (D103). Cada item do roteiro é uma `Resposta`
ou uma exceção (`ErroDeRede`, `ErroFatal`), levantada na vez dela.
"""

import json

from agente_contrato.chamada_llm import Resposta
from agente_contrato.registro_llm import Uso


def resposta(texto: str | None, stop_reason: str = "end_turn", entrada: int = 6000, saida: int = 500,
             thinking: int | None = None) -> Resposta:
    return Resposta(texto, stop_reason, "claude-haiku-5-5", Uso(entrada, saida, thinking), "req_falso", 0.01)


def classificacao(rotulo: str, justificativa: str = "porque sim", **kw) -> Resposta:
    return resposta(json.dumps({"rotulo": rotulo, "justificativa": justificativa}), **kw)


def reparo(metodo: str, **kw) -> Resposta:
    return resposta(json.dumps({"metodo_reparado": metodo}), **kw)


class ClienteFalso:
    def __init__(self, roteiro: list):
        self.roteiro = list(roteiro)
        self.chamadas: list[tuple[str, str, dict]] = []

    def chamar(self, sistema: str, usuario: str, schema: dict) -> Resposta:
        self.chamadas.append((sistema, usuario, schema))
        if not self.roteiro:
            raise AssertionError("o roteiro do cliente falso acabou: chamada inesperada")
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def contar_tokens(self, sistema: str, usuario: str) -> int:
        return (len(sistema) + len(usuario)) // 4
