"""Chamada ao LLM na v1 do Agente 1: SDK oficial, parâmetros fixos e tradução dos erros (D61, D104).

O restante do código só conhece `Resposta`, `ErroDeRede` e `ErroFatal`; o SDK fica isolado
aqui, e os testes trocam o cliente por um falso (`tests/fakes.py`). Nenhum teste automatizado
chama a API paga (D103).

Parâmetros iguais para os dois agentes do estudo (D61): sem `temperature`, `top_p` nem
`top_k` (o modelo só aceita o valor padrão), `effort` medium e `max_tokens` 16000, que
também limita o raciocínio.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .registro_llm import Uso

MODELO = "claude-haiku-5-5"  # D56
MAX_TOKENS = 16_000          # D61
EFFORT = "medium"            # D61
TIMEOUT_S = 120              # D104: valor inicial, a medir na T09
MAX_RETRIES_SDK = 2          # D104: o padrão do SDK, mantido; as repetições internas não vão para o log
NOME_DA_CHAVE = "ANTHROPIC_API_KEY"

_ERROS_DE_CLIENTE_QUE_SE_REPETEM = (408, 409)


class ErroDeRede(Exception):
    """O SDK desistiu por erro transitório (conexão, timeout, 408, 409, 429 com retry-after, 5xx).

    O caso é reexecutado uma vez; se falhar de novo, o registro leva `erro_llm` (D104).
    """

    def __init__(self, motivo: str, latencia_s: float):
        super().__init__(motivo)
        self.motivo, self.latencia_s = motivo, latencia_s


class ErroFatal(Exception):
    """Erro que repetir não resolve (400, 401, 402, 403, 429 sem retry-after, outros 4xx).

    A execução inteira para (D104). O 400 inclui o limite de gasto do workspace.
    """

    def __init__(self, motivo: str, latencia_s: float):
        super().__init__(motivo)
        self.motivo, self.latencia_s = motivo, latencia_s


class ChaveAusente(Exception):
    pass


@dataclass(frozen=True)
class Resposta:
    texto: str | None   # primeiro bloco de texto; o thinking não vem aqui
    stop_reason: str | None
    modelo: str | None
    uso: Uso
    request_id: str | None
    latencia_s: float


def e_fatal(status_code: int, tem_retry_after: bool) -> bool:
    """Decide se um erro HTTP que sobrou depois das tentativas do SDK é transitório.

    A D104 lista como não transitórios 400, 401, 402, 403 e 429 sem `retry-after` (teto do
    tier). Os demais 4xx (404, 413, 422...) também não se resolvem repetindo, então param a
    execução; isso estende a lista da D104 num ponto que ela não cobria.
    """
    if status_code >= 500 or status_code in _ERROS_DE_CLIENTE_QUE_SE_REPETEM:
        return False
    if status_code == 429:
        return not tem_retry_after
    return True


def ler_chave(caminho: Path) -> str:
    """Lê a chave de um `.env` local. É o único lugar de onde o código a obtém.

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


class ClienteAnthropic:
    def __init__(self, api_key: str, sdk=None):
        # `api_key` explícita: o SDK não cai na variável de ambiente por conta própria.
        self._sdk = sdk or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=MAX_RETRIES_SDK)

    def _traduzindo_erros(self, funcao, **parametros):
        inicio = time.monotonic()
        try:
            return funcao(**parametros), time.monotonic() - inicio
        except anthropic.APIConnectionError as e:  # inclui APITimeoutError
            raise ErroDeRede(f"{type(e).__name__}", time.monotonic() - inicio) from None
        except anthropic.APIStatusError as e:
            latencia = time.monotonic() - inicio
            motivo = f"HTTP {e.status_code} {type(e).__name__}: {e.message}"
            if e_fatal(e.status_code, e.response.headers.get("retry-after") is not None):
                raise ErroFatal(motivo, latencia) from None
            raise ErroDeRede(motivo, latencia) from None

    def chamar(self, sistema: str, usuario: str, schema: dict) -> Resposta:
        msg, latencia = self._traduzindo_erros(
            self._sdk.messages.create, model=MODELO, max_tokens=MAX_TOKENS, system=sistema,
            messages=[{"role": "user", "content": usuario}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}})
        detalhes = getattr(msg.usage, "output_tokens_details", None)
        uso = Uso(msg.usage.input_tokens, msg.usage.output_tokens, getattr(detalhes, "thinking_tokens", None))
        texto = next((b.text for b in msg.content if b.type == "text"), None)
        return Resposta(texto, msg.stop_reason, msg.model, uso, getattr(msg, "_request_id", None), latencia)

    def contar_tokens(self, sistema: str, usuario: str) -> int:
        """Contagem gratuita de tokens de entrada (D105, etapa 1). É uma estimativa da API."""
        contagem, _ = self._traduzindo_erros(
            self._sdk.messages.count_tokens, model=MODELO, system=sistema,
            messages=[{"role": "user", "content": usuario}])
        return contagem.input_tokens
