"""Leitura da diferença entre dois contratos OpenAPI (evidência do Agente 1).

Código determinístico. No T09 a mesma lista de mudanças será a evidência que o
Classifier recebe; só a decisão sobre ela passa a ser do LLM.

Limite conhecido: só são comparados o corpo da requisição e o corpo das
respostas 2xx. Parâmetros de caminho e de consulta não entram.
"""

import json
from dataclasses import dataclass
from pathlib import Path

REQUISICAO = "requisicao"
RESPOSTA = "resposta"

RENOMEACAO = "renomeacao"
REMOCAO = "remocao"
ALTERACAO_TIPO = "alteracao_tipo"
CAMPO_OBRIGATORIO_NOVO = "campo_obrigatorio_novo"

_METODOS_HTTP = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True)
class Propriedade:
    tipo: str
    formato: str | None
    enum: tuple[str, ...] | None
    obrigatoria: bool


@dataclass(frozen=True)
class Mudanca:
    tipo: str
    metodo: str
    rota: str
    lado: str
    caminho: str
    novo_caminho: str | None = None
    antes: Propriedade | None = None
    depois: Propriedade | None = None


def carregar(caminho_arquivo: str | Path) -> dict:
    return json.loads(Path(caminho_arquivo).read_text(encoding="utf-8"))


def _resolver(contrato: dict, no: dict, pilha: tuple[str, ...]) -> tuple[dict, tuple[str, ...]]:
    ref = no.get("$ref")
    if ref is None:
        return no, pilha
    nome = ref.rsplit("/", 1)[-1]
    if nome in pilha:
        return {}, pilha  # referência circular: não desce de novo
    return contrato["components"]["schemas"][nome], pilha + (nome,)


def _achatar_schema(contrato: dict, no: dict, prefixo: str, obrigatoria: bool,
                    pilha: tuple[str, ...], saida: dict[str, Propriedade]) -> None:
    schema, pilha = _resolver(contrato, no, pilha)
    tipo = schema.get("type", "object" if "properties" in schema else "desconhecido")
    enum = tuple(schema["enum"]) if "enum" in schema else None
    if prefixo:
        saida[prefixo] = Propriedade(tipo, schema.get("format"), enum, obrigatoria)
    if tipo == "array" and "items" in schema:
        _achatar_schema(contrato, schema["items"], prefixo + "[]", False, pilha, saida)
    obrigatorias = set(schema.get("required", []))
    for nome, filho in schema.get("properties", {}).items():
        caminho = f"{prefixo}.{nome}" if prefixo else nome
        _achatar_schema(contrato, filho, caminho, nome in obrigatorias, pilha, saida)


def _schema_json(conteudo: dict) -> dict | None:
    for midia in conteudo.values():
        if "schema" in midia:
            return midia["schema"]
    return None


def achatar(contrato: dict) -> dict[tuple[str, str, str], dict[str, Propriedade]]:
    """Mapeia (método, rota, lado) para {caminho do campo: Propriedade}."""
    resultado: dict[tuple[str, str, str], dict[str, Propriedade]] = {}
    for rota, operacoes in contrato.get("paths", {}).items():
        for metodo in _METODOS_HTTP:
            operacao = operacoes.get(metodo)
            if operacao is None:
                continue
            schemas = []
            corpo = _schema_json(operacao.get("requestBody", {}).get("content", {}))
            if corpo is not None:
                schemas.append((REQUISICAO, corpo))
            for status, resp in operacao.get("responses", {}).items():
                if status.startswith("2"):
                    schema = _schema_json(resp.get("content", {}))
                    if schema is not None:
                        schemas.append((RESPOSTA, schema))
            for lado, schema in schemas:
                campos: dict[str, Propriedade] = {}
                _achatar_schema(contrato, schema, "", False, (), campos)
                resultado[(metodo.upper(), rota, lado)] = campos
    return resultado


def _pai(caminho: str) -> str:
    return caminho.rsplit(".", 1)[0] if "." in caminho else ""


def _debaixo_de(caminho: str, removidos: set[str]) -> bool:
    return any(caminho.startswith(r + ".") or caminho.startswith(r + "[]") for r in removidos)


def _mesma_forma(a: Propriedade, b: Propriedade) -> bool:
    return a.tipo == b.tipo and a.enum == b.enum


def diferenca(antigo: dict, novo: dict) -> list[Mudanca]:
    """Lista as mudanças de contrato por operação, na ordem (método, rota, lado, caminho).

    Renomeação: dentro do mesmo objeto, exatamente um campo removido e um adicionado
    com a mesma forma (tipo e enum; o formato, como int32 e int64, não conta). Havendo mais de um candidato, não se
    adivinha: viram remoção e campo novo.
    """
    campos_antigos = achatar(antigo)
    campos_novos = achatar(novo)
    mudancas: list[Mudanca] = []
    for chave in sorted(set(campos_antigos) & set(campos_novos)):
        metodo, rota, lado = chave
        velhos, novos = campos_antigos[chave], campos_novos[chave]
        removidos = {c for c in velhos if c not in novos}
        adicionados = {c for c in novos if c not in velhos}
        # Descendentes de um campo que sumiu ou apareceu acompanham o pai.
        removidos_raiz = {c for c in removidos if not _debaixo_de(c, removidos)}
        adicionados_raiz = {c for c in adicionados if not _debaixo_de(c, adicionados)}

        for pai in sorted({_pai(c) for c in removidos_raiz | adicionados_raiz}):
            r = sorted(c for c in removidos_raiz if _pai(c) == pai)
            a = sorted(c for c in adicionados_raiz if _pai(c) == pai)
            if len(r) == 1 and len(a) == 1 and _mesma_forma(velhos[r[0]], novos[a[0]]):
                mudancas.append(Mudanca(RENOMEACAO, metodo, rota, lado, r[0], a[0],
                                        velhos[r[0]], novos[a[0]]))
                continue
            for c in r:
                mudancas.append(Mudanca(REMOCAO, metodo, rota, lado, c, antes=velhos[c]))
            for c in a:
                if novos[c].obrigatoria:
                    mudancas.append(Mudanca(CAMPO_OBRIGATORIO_NOVO, metodo, rota, lado, c,
                                            depois=novos[c]))

        for c in sorted(set(velhos) & set(novos)):
            if not _mesma_forma(velhos[c], novos[c]):
                mudancas.append(Mudanca(ALTERACAO_TIPO, metodo, rota, lado, c,
                                        antes=velhos[c], depois=novos[c]))
            elif novos[c].obrigatoria and not velhos[c].obrigatoria:
                mudancas.append(Mudanca(CAMPO_OBRIGATORIO_NOVO, metodo, rota, lado, c,
                                        antes=velhos[c], depois=novos[c]))
    return mudancas
