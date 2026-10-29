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


def achatar_schema(contrato: dict, no: dict, prefixo: str = "", obrigatoria: bool = False,
                   visitados: tuple[str, ...] = ()) -> dict[str, Propriedade]:
    """Transforma a árvore de um schema em {caminho do campo: Propriedade}, como `cliente.endereco.cep`.

    O item de uma lista ganha `[]` no caminho (`itens[].quantidade`); a raiz, de prefixo vazio, não entra.
    """
    schema, visitados = resolver(contrato, no, visitados)
    tipo = schema.get("type", "object" if "properties" in schema else "desconhecido")
    campos = {}
    if prefixo:
        enum = tuple(schema["enum"]) if "enum" in schema else None
        campos[prefixo] = Propriedade(tipo, schema.get("format"), enum, obrigatoria)
    if tipo == "array" and "items" in schema:
        campos.update(achatar_schema(contrato, schema["items"], prefixo + "[]", False, visitados))
    obrigatorias = set(schema.get("required", []))
    for nome, filho in schema.get("properties", {}).items():
        caminho = f"{prefixo}.{nome}" if prefixo else nome
        campos.update(achatar_schema(contrato, filho, caminho, nome in obrigatorias, visitados))
    return campos
