"""Chamada real ao Claude na versão agêntica do Agente 1 (T23i): SDK oficial, sem framework (D58).

O laço (`rodar_laco`) não conhece a API: ele recebe uma `RespostaModelo` e devolve resultados de
ferramenta. Este módulo traduz de um formato para o outro, faz a chamada com os parâmetros da D61,
traduz o `stop_reason` e os erros HTTP (D102, D104, D108, D117c) e grava uma linha de log por
chamada (D106, D107). Nenhum teste automatizado chama a API paga: os testes trocam o SDK por um falso.
"""
import json
import time
from pathlib import Path

import anthropic

from agente_contrato.laco import PedidoFerramenta, RespostaModelo
from agente_contrato.prompts import carregar
from agente_contrato.registro_llm import LogDeChamadas, PromptAcimaDoLimite, custo_usd, uso_da_resposta

MODELO = "claude-haiku-5-5"  # D56
MAX_TOKENS = 16_000          # D61: teto por resposta; o raciocínio conta nele
EFFORT = "medium"            # D61: o padrão do modelo, escrito para ficar registrado
TIMEOUT_S = 120              # D104, D111(c): timeout explícito de cada chamada
MAX_RETRIES_SDK = 2          # D104: o padrão do SDK; as repetições internas não vão para o log

# D102, D117c: o código de erro (campo `erro` da D74) de cada stop_reason que encerra o caso
SAIDA_INVALIDA = "saida_invalida"
CORTADA = "max_tokens"
_PARADAS_ESPERADAS = {"end_turn", "tool_use"}

NOME_DA_CHAVE = "ANTHROPIC_API_KEY"
_ERROS_DE_CLIENTE_QUE_SE_REPETEM = (408, 409)


class RespostaInvalida(Exception):
    """O modelo parou de um jeito que encerra o caso; `codigo` é o `erro` da D74 e `motivo` vai para o log.

    O laço não conhece `stop_reason`, então a exceção atravessa o `rodar_laco` sem mudá-lo, e quem
    chama o agente (o runner, T23j) registra o código.
    """

    def __init__(self, codigo: str, motivo: str):
        super().__init__(motivo)
        self.codigo, self.motivo = codigo, motivo


class ErroDeRede(Exception):
    """O SDK desistiu por erro transitório (conexão, timeout, 408, 409, 429 com retry-after, 5xx).

    O caso é reexecutado uma vez; se falhar de novo, o registro leva `erro_llm` (D104). Igual à v1.
    """

    def __init__(self, motivo: str, latencia_s: float):
        super().__init__(motivo)
        self.motivo, self.latencia_s = motivo, latencia_s


class ErroFatal(Exception):
    """Erro que repetir não resolve (400, 401, 402, 403, 429 sem retry-after e os outros 4xx).

    A execução inteira para (D104, D108). O 400 inclui o limite de gasto do workspace. Igual à v1.
    """

    def __init__(self, motivo: str, latencia_s: float):
        super().__init__(motivo)
        self.motivo, self.latencia_s = motivo, latencia_s


class ChaveAusente(Exception):
    pass


def e_fatal(status_code: int, tem_retry_after: bool) -> bool:
    """Se um erro HTTP que sobrou depois das tentativas do SDK para a execução (D104, D108). Igual à v1."""
    if status_code >= 500 or status_code in _ERROS_DE_CLIENTE_QUE_SE_REPETEM:
        return False
    if status_code == 429:
        return not tem_retry_after  # sem retry-after, é o teto do tier
    return True


def chamar_traduzindo(funcao, **parametros_da_chamada):
    """Chama o SDK e devolve (resultado, latência em s); um erro vira ErroDeRede ou ErroFatal. Igual à v1."""
    inicio = time.monotonic()
    try:
        return funcao(**parametros_da_chamada), time.monotonic() - inicio
    except anthropic.APIConnectionError as e:  # inclui APITimeoutError
        raise ErroDeRede(type(e).__name__, time.monotonic() - inicio) from None
    except anthropic.APIStatusError as e:
        latencia = time.monotonic() - inicio
        motivo = f"HTTP {e.status_code} {type(e).__name__}: {e.message}"
        if e_fatal(e.status_code, e.response.headers.get("retry-after") is not None):
            raise ErroFatal(motivo, latencia) from None
        raise ErroDeRede(motivo, latencia) from None


def ler_chave(caminho: Path) -> str:
    """Lê a chave de um `.env` local, o único lugar de onde o código a obtém. Igual à v1.

    As mensagens de erro dizem o que falta, nunca o conteúdo do arquivo.
    """
    if not caminho.is_file():
        raise ChaveAusente(f"{caminho} não existe: copie .env.example para .env e preencha a chave")
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        nome, separador, valor = linha.strip().partition("=")
        if separador and nome.strip() == NOME_DA_CHAVE:
            valor = valor.strip().strip("\"'")
            if valor:
                return valor
    raise ChaveAusente(f"{NOME_DA_CHAVE} ausente ou vazia em {caminho}")


def criar_sdk(api_key: str, timeout_s: float = TIMEOUT_S) -> anthropic.Anthropic:
    """O cliente do SDK com o timeout explícito e as 2 repetições da D104; só constrói, não chama a rede.

    `api_key` explícita: o SDK não cai na variável de ambiente por conta própria.
    """
    return anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=MAX_RETRIES_SDK)


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


def _para_o_log(blocos: list) -> str:
    """O `content` da resposta como texto JSON para o campo `resposta_bruta`.

    Texto e pedidos entram inteiros; do pensamento só entra o tipo, porque a assinatura é opaca e
    não ajuda a ler o log.
    """
    def bloco(b) -> dict:
        if b.type == "text":
            return {"type": "text", "text": b.text}
        if b.type == "tool_use":
            return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
        return {"type": b.type}
    return json.dumps([bloco(b) for b in blocos], ensure_ascii=False)


class ModeloClaude:
    """O modelo que o `rodar_laco` chama, no lugar do LLM simulado: recebe o histórico e devolve uma
    RespostaModelo (T23i). O laço não muda.

    Cada chamada grava uma linha no log antes de qualquer outra coisa, inclusive quando dá erro
    (D106). Os erros saem como exceções que atravessam o laço: ErroDeRede e ErroFatal (D104, D108),
    RespostaInvalida (D102, D117c) e PromptAcimaDoLimite (D106).
    """

    def __init__(self, sdk, sistema: str, definicoes: list[dict], etapa: str, log: LogDeChamadas,
                 id_caso: str, repeticao: int, commit_do_prompt: str, formato: dict | None = None):
        self._sdk, self._sistema, self._definicoes, self._formato = sdk, sistema, definicoes, formato
        self._log, self._etapa = log, etapa
        self._id_caso, self._repeticao, self._commit = id_caso, repeticao, commit_do_prompt
        self._brutos = []  # o `content` de cada resposta, reenviado sem mudança (ver `mensagens`)

    def __call__(self, historico: list) -> RespostaModelo:
        enviados = parametros(self._sistema, self._definicoes, mensagens(historico, self._brutos), self._formato)
        try:
            msg, latencia = chamar_traduzindo(self._sdk.messages.create, **enviados)
        except (ErroDeRede, ErroFatal) as e:  # sem resposta: sem tokens e sem custo
            self._registrar(erro=e.motivo, latencia_s=e.latencia_s, custo_usd=0.0)
            raise
        uso = uso_da_resposta(msg.usage)
        campos = dict(modelo_retornado=msg.model, stop_reason=msg.stop_reason, input_tokens=uso.input_tokens,
                      output_tokens=uso.output_tokens, thinking_tokens=uso.thinking_tokens,
                      request_id=getattr(msg, "_request_id", None), latencia_s=round(latencia, 3),
                      resposta_bruta=_para_o_log(msg.content))
        try:
            custo = custo_usd(uso)
        except PromptAcimaDoLimite as e:  # a chamada já foi paga: grava a linha e só então para (D106)
            self._registrar(**campos, custo_usd=None, erro=str(e))
            raise
        try:
            resposta = ler_resposta(msg.stop_reason, msg.content)
        except RespostaInvalida as e:
            self._registrar(**campos, custo_usd=custo, erro=e.motivo)
            raise
        self._registrar(**campos, custo_usd=custo, erro=None)
        self._brutos.append(msg.content)
        return resposta

    def _registrar(self, **campos) -> None:
        vazios = dict(modelo_retornado=None, stop_reason=None, input_tokens=None, output_tokens=None,
                      thinking_tokens=None, request_id=None, resposta_bruta=None)
        self._log.registrar(**{**vazios, **campos}, id_caso=self._id_caso, repeticao=self._repeticao,
                            etapa=self._etapa, commit_do_prompt=self._commit)


class FabricaClaude:
    """Faz o papel do `criar_modelo(sistema, definicoes, formato)` com o Claude de verdade, numa execução.

    O runner (T23j) cria uma fábrica por execução (caso e repetição); a etapa do log sai do prompt de
    sistema que o agente mandou.
    """

    def __init__(self, sdk, log: LogDeChamadas, id_caso: str, repeticao: int, commit_do_prompt: str):
        self._sdk, self._log = sdk, log
        self._id_caso, self._repeticao, self._commit = id_caso, repeticao, commit_do_prompt
        self._etapas = {carregar(etapa): etapa for etapa in ("classifier", "repair")}

    def __call__(self, sistema: str, definicoes: list[dict], formato: dict | None = None) -> ModeloClaude:
        etapa = self._etapas.get(sistema)
        if etapa is None:
            raise ValueError("prompt de sistema que não é nem o do Classifier nem o do Repair")
        return ModeloClaude(self._sdk, sistema, definicoes, etapa, self._log, self._id_caso, self._repeticao,
                            self._commit, formato)
