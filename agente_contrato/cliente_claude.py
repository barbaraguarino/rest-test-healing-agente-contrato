"""Chamada real ao Claude na versão agêntica do Agente 1 (T23i): SDK oficial, sem framework (D58).

O laço (`rodar_laco`) não conhece a API: ele recebe uma `RespostaModelo` e devolve resultados de
ferramenta. Este módulo traduz de um formato para o outro, faz a chamada com os parâmetros da D61,
traduz o `stop_reason` e os erros HTTP (D102, D104, D108, D117c) e grava uma linha de log por
chamada (D106, D107). Nenhum teste automatizado chama a API paga: os testes trocam o SDK por um falso.
"""
from agente_contrato.laco import PedidoFerramenta, RespostaModelo

MODELO ="claude-haiku-5-5"  # D56
MAX_TOKENS = 16_000          # D61: teto por resposta; o raciocínio conta nele
EFFORT = "medium"            # D61: o padrão do modelo, escrito para ficar registrado
TIMEOUT_S = 120              # D104, D111(c): timeout explícito de cada chamada
MAX_RETRIES_SDK = 2          # D104: o padrão do SDK; as repetições internas não vão para o log

# D102, D117c: o código de erro (campo `erro` da D74) de cada stop_reason que encerra o caso
SAIDA_INVALIDA = "saida_invalida"
CORTADA = "max_tokens"
_PARADAS_ESPERADAS = {"end_turn", "tool_use"}


class RespostaInvalida(Exception):
    """O modelo parou de um jeito que encerra o caso; `codigo` é o `erro` da D74 e `motivo` vai para o log.

    O laço não conhece `stop_reason`, então a exceção atravessa o `rodar_laco` sem mudá-lo, e quem
    chama o agente (o runner, T23j) registra o código.
    """

    def __init__(self, codigo: str, motivo: str):
        super().__init__(motivo)
        self.codigo, self.motivo = codigo, motivo


def parametros(sistema: str, definicoes: list[dict], mensagens: list[dict], formato: dict | None = None) -> dict:
    """Os argumentos de `messages.create`, iguais para os dois agentes (D61).

    Sem `temperature`, `top_p` e `top_k` (o claude-haiku-5-5 recusa valores fora do padrão) e sem
    `thinking` (o pensamento adaptativo fica no padrão). `formato` é o schema JSON da resposta final;
    só o Classifier o envia (D131).
    """
    output_config = {"effort": EFFORT}
    if formato is not None:
        output_config["format"] = {"type": "json_schema", "schema": formato}
    return {"model": MODELO, "max_tokens": MAX_TOKENS, "system": sistema, "tools": definicoes,
            "messages": mensagens, "output_config": output_config}


def para_resposta(blocos: list) -> RespostaModelo:
    """Os blocos de `content` da API viram a RespostaModelo que o laço conhece.

    O texto junta os blocos `text`; cada `tool_use` vira um pedido. Os blocos `thinking` não entram
    aqui: o laço não os usa, e eles voltam à API pelo `content` guardado (ver `mensagens`).
    """
    texto = "".join(b.text for b in blocos if b.type == "text")
    pedidos = tuple(PedidoFerramenta(b.id, b.name, b.input) for b in blocos if b.type == "tool_use")
    return RespostaModelo(texto, pedidos)


def ler_resposta(stop_reason: str | None, blocos: list) -> RespostaModelo:
    """Confere o `stop_reason` e só então traduz os blocos (D102, D117c).

    `end_turn` e `tool_use` seguem para o laço. `max_tokens` é `max_tokens`; `refusal`,
    `model_context_window_exceeded` e qualquer outro motivo são `saida_invalida`. Também é
    `saida_invalida` o motivo que não combina com os blocos: `tool_use` sem pedido (o laço acharia
    que o modelo terminou) ou `end_turn` com pedido (o laço executaria um pedido que a API não fez).
    """
    if stop_reason == "max_tokens":
        raise RespostaInvalida(CORTADA, "resposta cortada no max_tokens")
    if stop_reason not in _PARADAS_ESPERADAS:
        raise RespostaInvalida(SAIDA_INVALIDA, f"stop_reason {stop_reason}")
    resposta = para_resposta(blocos)
    if resposta.terminou != (stop_reason == "end_turn"):
        raise RespostaInvalida(SAIDA_INVALIDA, f"stop_reason {stop_reason} com {len(resposta.pedidos)} pedido(s)")
    return resposta


def mensagens(historico: list, brutos: list) -> list[dict]:
    """O histórico do laço no formato `messages` da API.

    O histórico alterna: a mensagem inicial (texto), uma RespostaModelo, os resultados das
    ferramentas, outra RespostaModelo... `brutos` tem o `content` de cada resposta do modelo, na
    mesma ordem, e é ele que volta como mensagem do assistente, sem nenhuma mudança: o claude-haiku-5-5
    só aproveita os blocos de pensamento reenviados exatamente como vieram.
    """
    saida, respostas = [], iter(brutos)
    for item in historico:
        if isinstance(item, str):
            saida.append({"role": "user", "content": item})
        elif isinstance(item, RespostaModelo):
            saida.append({"role": "assistant", "content": next(respostas)})
        else:  # tupla de ResultadoFerramenta; o erro volta como is_error (D124)
            saida.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r.id_pedido, "content": r.conteudo, "is_error": r.erro}
                for r in item]})
    return saida
