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
