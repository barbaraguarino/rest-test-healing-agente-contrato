"""Validação da saída do LLM na v1 do Agente 1 (D101, D102).

O modelo só devolve texto; este módulo decide se esse texto é aproveitável e, se não for,
com qual código de erro da D74 o caso termina. Não há nova tentativa (D102).

A ordem das verificações importa: primeiro o `stop_reason`, depois o JSON. Uma resposta
cortada por `max_tokens` quase sempre é um JSON incompleto, e se o JSON fosse lido antes
ela seria contada como `saida_invalida` em vez de `max_tokens`.
"""

import json
from dataclasses import dataclass

from . import teste_java as tj

LEGITIMA = "legitima"
PROBLEMA_REAL = "problema_real"
ROTULOS = (LEGITIMA, PROBLEMA_REAL)

# Valores do campo `erro` da D74 que este módulo produz.
SAIDA_INVALIDA = "saida_invalida"
MAX_TOKENS = "max_tokens"

# Schemas enviados em `output_config.format`. A API não aceita `minLength`/`maxLength`,
# então "1 a 2 frases" fica no prompt e "método não vazio" é conferido aqui.
SCHEMA_CLASSIFIER = {
    "type": "object",
    "properties": {
        "rotulo": {"type": "string", "enum": list(ROTULOS)},
        "justificativa": {"type": "string"},
    },
    "required": ["rotulo", "justificativa"],
    "additionalProperties": False,
}
SCHEMA_REPAIR = {
    "type": "object",
    "properties": {"metodo_reparado": {"type": "string"}},
    "required": ["metodo_reparado"],
    "additionalProperties": False,
}

_PARADAS_SEM_SAIDA = {"refusal", "model_context_window_exceeded"}


class SaidaRejeitada(Exception):
    """A saída não serve; `codigo` é o valor do campo `erro` da D74 e `motivo` vai para o log."""

    def __init__(self, codigo: str, motivo: str):
        super().__init__(motivo)
        self.codigo = codigo
        self.motivo = motivo


@dataclass(frozen=True)
class Classificacao:
    rotulo: str
    justificativa: str


def _verificar_parada(stop_reason: str | None) -> None:
    if stop_reason == "max_tokens":
        raise SaidaRejeitada(MAX_TOKENS, "resposta cortada por max_tokens")
    if stop_reason in _PARADAS_SEM_SAIDA:
        raise SaidaRejeitada(SAIDA_INVALIDA, f"stop_reason {stop_reason}")
    if stop_reason != "end_turn":  # sem stop sequences nem ferramentas, só end_turn é esperado
        raise SaidaRejeitada(SAIDA_INVALIDA, f"stop_reason inesperado: {stop_reason!r}")


def _objeto(stop_reason: str | None, texto: str | None, campos: set[str]) -> dict:
    _verificar_parada(stop_reason)
    if not texto:
        raise SaidaRejeitada(SAIDA_INVALIDA, "resposta sem texto")
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:
        raise SaidaRejeitada(SAIDA_INVALIDA, f"JSON ilegível: {e.msg}") from None
    if not isinstance(dados, dict) or set(dados) != campos:
        raise SaidaRejeitada(SAIDA_INVALIDA, f"campos esperados {sorted(campos)}, recebidos "
                                             f"{sorted(dados) if isinstance(dados, dict) else type(dados).__name__}")
    return dados


def ler_classificacao(stop_reason: str | None, texto: str | None) -> Classificacao:
    dados = _objeto(stop_reason, texto, {"rotulo", "justificativa"})
    rotulo, justificativa = dados["rotulo"], dados["justificativa"]
    if not isinstance(rotulo, str) or not isinstance(justificativa, str):
        raise SaidaRejeitada(SAIDA_INVALIDA, "rotulo e justificativa devem ser texto")
    # A API não garante maiúsculas e minúsculas em enum (D101): compara sem diferenciá-las.
    normalizado = rotulo.strip().lower()
    if normalizado not in ROTULOS:
        raise SaidaRejeitada(SAIDA_INVALIDA, f"rótulo fora de {ROTULOS}: {rotulo!r}")
    return Classificacao(normalizado, justificativa.strip())


def ler_reparo(stop_reason: str | None, texto: str | None) -> str:
    metodo = _objeto(stop_reason, texto, {"metodo_reparado"})["metodo_reparado"]
    if not isinstance(metodo, str) or not metodo.strip():
        raise SaidaRejeitada(SAIDA_INVALIDA, "metodo_reparado vazio")
    return metodo


def encaixar(original: str, nome_metodo: str, metodo_reparado: str) -> str:
    """Troca só o corpo do método no arquivo original pelo corpo do método devolvido.

    Anotações e assinatura continuam as do original, então o modelo não consegue mudar a
    fixture `@Sql` nem o nome do teste. Um método que não é achado, ou com chaves
    desbalanceadas, vira `saida_invalida` (D102).
    """
    try:
        novo = tj.localizar_metodo(metodo_reparado, nome_metodo)
    except tj.ErroDeAnalise as e:
        raise SaidaRejeitada(SAIDA_INVALIDA, f"metodo_reparado não encaixa: {e}") from None
    antigo = tj.localizar_metodo(original, nome_metodo)  # o original é nosso: erro aqui é bug
    return original[:antigo.inicio] + metodo_reparado[novo.inicio:novo.fim] + original[antigo.fim:]
