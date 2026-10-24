"""Custo, trava de orçamento e log das chamadas ao LLM na v1 (D105, D106).

O custo é calculado pelo código a partir dos tokens que a API devolve, nunca estimado pelo
modelo. O log é um arquivo JSON Lines com uma linha por chamada, gravada e descarregada na
hora: uma queda ou a parada por orçamento não perde nenhuma chamada paga.
"""

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

LIMITE_PROMPT_TOKENS = 100_000  # acima disso a tabela de preços muda (D106)
ETAPAS = ("classifier", "repair")
CAMPOS_DO_LOG = ("id_caso", "repeticao", "etapa", "modelo_retornado", "stop_reason", "input_tokens",
                 "output_tokens", "thinking_tokens", "custo_usd", "request_id", "latencia_s",
                 "commit_do_prompt", "resposta_bruta", "erro")


@dataclass(frozen=True)
class Preco:
    """Dólares por milhão de tokens e a fonte, para o pacote de replicação."""
    entrada: Decimal
    saida: Decimal
    fonte: str
    consultado_em: str


# D56/D105: claude-haiku-5-5, prompts de até 100 mil tokens.
PRECO_HAIKU_5_5 = Preco(Decimal("0.10"), Decimal("0.50"),
                        "platform.claude.com/docs/en/about-claude/pricing", "2026-10-22")


class PromptAcimaDoLimite(Exception):
    """O prompt passou de 100 mil tokens: o preço da fonte não vale mais (D106)."""


class OrcamentoEsgotado(Exception):
    """O gasto acumulado chegou ao limite da rodada (`--orcamento-usd`, D105)."""

    def __init__(self, gasto: float, limite: float):
        super().__init__(f"gasto de US$ {gasto:.6f} chegou ao limite de US$ {limite:g}")
        self.gasto, self.limite = gasto, limite


@dataclass(frozen=True)
class Uso:
    input_tokens: int
    output_tokens: int           # a documentação diz que inclui os tokens de thinking; a etapa 2 confere
    thinking_tokens: int | None  # usage.output_tokens_details.thinking_tokens, se a API informar

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


def custo_usd(uso: Uso, preco: Preco = PRECO_HAIKU_5_5) -> float:
    """(entrada × preço de entrada + saída × preço de saída) / 1 milhão."""
    if uso.input_tokens < 0 or uso.output_tokens < 0:
        raise ValueError("tokens negativos")
    if uso.input_tokens > LIMITE_PROMPT_TOKENS:
        raise PromptAcimaDoLimite(f"{uso.input_tokens} tokens de entrada (limite {LIMITE_PROMPT_TOKENS})")
    bruto = (Decimal(uso.input_tokens) * preco.entrada + Decimal(uso.output_tokens) * preco.saida) / 1_000_000
    return float(bruto)


class Orcamento:
    """Acumula o gasto da rodada e impede novas chamadas depois do limite.

    A conferência é antes de cada chamada, então o gasto pode passar do limite por, no
    máximo, uma chamada (cerca de US$ 0,009 no pior caso, com 16 mil tokens de saída).
    """

    def __init__(self, limite_usd: float, gasto_usd: float = 0.0, tokens: int = 0):
        """`gasto_usd` e `tokens`: o que a mesma rodada já gastou antes de ser retomada (`gasto_do_log`)."""
        if limite_usd <= 0:
            raise ValueError("o limite de orçamento deve ser positivo")
        self.limite_usd = limite_usd
        self.gasto_usd = gasto_usd
        self.tokens = tokens

    def somar(self, uso: Uso, custo: float) -> None:
        self.gasto_usd += custo
        self.tokens += uso.total

    def verificar(self) -> None:
        if self.gasto_usd >= self.limite_usd:
            raise OrcamentoEsgotado(self.gasto_usd, self.limite_usd)


class LogDeChamadas:
    """Uma linha JSON por chamada, em modo append e com fsync."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)

    def registrar(self, **campos) -> None:
        if set(campos) != set(CAMPOS_DO_LOG):
            raise ValueError(f"campos do log: esperados {sorted(CAMPOS_DO_LOG)}, recebidos {sorted(campos)}")
        if campos["etapa"] not in ETAPAS:
            raise ValueError(f"etapa inválida: {campos['etapa']!r}")
        linha = json.dumps({c: campos[c] for c in CAMPOS_DO_LOG}, ensure_ascii=False)
        with open(self.caminho, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
            f.flush()
            os.fsync(f.fileno())


def gasto_do_log(caminho: Path) -> tuple[float, int]:
    """Dólares e tokens já registrados num `chamadas.jsonl` (zero se ele não existe).

    Na retomada da etapa 4, o orçamento começa daqui: a trava vale para a rodada inteira, e não
    para cada vez que o comando roda. Chamada que falhou sem resposta tem custo 0 e tokens nulos.
    """
    if not caminho.exists():
        return 0.0, 0
    gasto, tokens = Decimal(0), 0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        c = json.loads(linha)
        gasto += Decimal(str(c["custo_usd"] or 0))
        tokens += (c["input_tokens"] or 0) + (c["output_tokens"] or 0)
    return float(gasto), tokens
