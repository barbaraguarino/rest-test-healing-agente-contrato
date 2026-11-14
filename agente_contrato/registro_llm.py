"""Custo e log das chamadas ao Claude na versão agêntica (T23i, D106, D107), a partir dos da v1.

O custo é calculado pelo código a partir dos tokens que a API devolve, nunca estimado pelo modelo.
O log é um arquivo JSON Lines com uma linha por chamada, gravada e descarregada na hora: uma queda
não perde nenhuma chamada paga.
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


# D56: claude-haiku-5-5, prompts de até 100 mil tokens (mesma fonte e data da v1)
PRECO_HAIKU_5_5 = Preco(Decimal("0.10"), Decimal("0.50"),
                        "platform.claude.com/docs/en/about-claude/pricing", "2026-10-22")


class PromptAcimaDoLimite(Exception):
    """O prompt passou de 100 mil tokens: o preço da fonte não vale mais (D106)."""


@dataclass(frozen=True)
class Uso:
    input_tokens: int
    output_tokens: int           # inclui os tokens de pensamento (D107)
    thinking_tokens: int | None  # usage.output_tokens_details.thinking_tokens, se a API informar

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


def uso_da_resposta(usage) -> Uso:
    """O `usage` da resposta da API vira um Uso; `thinking_tokens` fica nulo se a API não informar."""
    detalhes = getattr(usage, "output_tokens_details", None)
    return Uso(usage.input_tokens, usage.output_tokens, getattr(detalhes, "thinking_tokens", None))


def custo_usd(uso: Uso, preco: Preco = PRECO_HAIKU_5_5) -> float:
    """(entrada × preço de entrada + saída × preço de saída) / 1 milhão. Igual à v1."""
    if uso.input_tokens < 0 or uso.output_tokens < 0:
        raise ValueError("tokens negativos")
    if uso.input_tokens > LIMITE_PROMPT_TOKENS:
        raise PromptAcimaDoLimite(f"{uso.input_tokens} tokens de entrada (limite {LIMITE_PROMPT_TOKENS})")
    bruto = (Decimal(uso.input_tokens) * preco.entrada + Decimal(uso.output_tokens) * preco.saida) / 1_000_000
    return float(bruto)


class LogDeChamadas:
    """Uma linha JSON por chamada, em modo append e com fsync. Igual à v1."""

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


def gasto_do_log(caminho: Path, id_caso: str | None = None, repeticao: int | None = None,
                 desde: int = 0) -> tuple[float, int]:
    """Dólares e tokens já registrados num `chamadas.jsonl` (zero se ele não existe). Da v1 (D105).

    Sem `id_caso`, soma o arquivo inteiro: é o gasto da rodada, que a trava de orçamento confere.
    Com `id_caso` e `repeticao`, soma só essa execução, com a reexecução (D104), que também é paga:
    são o `tokens` e o `custo_usd` do registro (D74). Chamada que falhou sem resposta tem custo 0 e
    tokens nulos. `desde`: pula as primeiras linhas do arquivo, as de sessões anteriores da mesma rodada
    (retomada, T53): as chamadas pagas de uma execução interrompida não entram no registro dela.
    """
    if not caminho.exists():
        return 0.0, 0
    gasto, tokens = Decimal(0), 0
    for linha in caminho.read_text(encoding="utf-8").splitlines()[desde:]:
        if not linha.strip():
            continue
        c = json.loads(linha)
        if id_caso is not None and (c["id_caso"], c["repeticao"]) != (id_caso, repeticao):
            continue
        gasto += Decimal(str(c["custo_usd"] or 0))
        tokens += (c["input_tokens"] or 0) + (c["output_tokens"] or 0)
    return float(gasto), tokens


class OrcamentoEsgotado(Exception):
    """O gasto da rodada chegou ao limite (`--orcamento-usd`, D105). Igual à v1."""

    def __init__(self, gasto: float, limite: float):
        super().__init__(f"gasto de US$ {gasto:.6f} chegou ao limite de US$ {limite:g}")
        self.gasto, self.limite = gasto, limite


class Orcamento:
    """A trava de orçamento da v1 (D105): conferida antes de cada chamada, nunca depois.

    Diferente da v1, não soma o gasto na memória: lê o `chamadas.jsonl` da rodada, que já tem cada
    chamada paga gravada na hora (D106). Assim a trava vale para a rodada inteira, inclusive quando
    o comando roda de novo na mesma pasta. O gasto pode passar do limite por, no máximo, uma chamada
    (cerca de US$ 0,009 no pior caso, com 16 mil tokens de saída).
    """

    def __init__(self, limite_usd: float, log: Path):
        if limite_usd <= 0:
            raise ValueError("o limite de orçamento deve ser positivo")
        self.limite_usd, self.log = limite_usd, log

    def gasto_usd(self) -> float:
        return gasto_do_log(self.log)[0]

    def verificar(self) -> None:
        gasto = self.gasto_usd()
        if gasto >= self.limite_usd:
            raise OrcamentoEsgotado(gasto, self.limite_usd)
