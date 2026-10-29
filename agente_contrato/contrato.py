"""Diferença entre o contrato OpenAPI antigo e o novo (T23d, D62, D100): a evidência do Agente 1.

Código determinístico: o LLM não decide nada aqui, só lê a lista de mudanças (ferramenta da T23e).
Limite conhecido, o mesmo da v1: só entram o corpo da requisição e o das respostas 2xx; parâmetros
de caminho e de consulta ficam de fora.
"""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Propriedade:
    """Um campo do contrato depois de achatado: tipo, formato, valores permitidos e se é obrigatório."""
    tipo: str
    formato: str | None
    enum: tuple[str, ...] | None
    obrigatoria: bool


def carregar(arquivo: Path) -> dict:
    return json.loads(Path(arquivo).read_text(encoding="utf-8"))


def resolver(contrato: dict, no: dict, visitados: tuple[str, ...]) -> tuple[dict, tuple[str, ...]]:
    """Segue um `$ref` até o schema em `components`; numa referência circular, devolve um schema vazio."""
    ref = no.get("$ref")
    if ref is None:
        return no, visitados
    nome = ref.rsplit("/", 1)[-1]
    if nome in visitados:
        return {}, visitados
    return contrato["components"]["schemas"][nome], visitados + (nome,)
