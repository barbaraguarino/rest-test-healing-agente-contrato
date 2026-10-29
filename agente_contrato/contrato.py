"""Diferença entre o contrato OpenAPI antigo e o novo (T23d, D62, D100): a evidência do Agente 1.

Código determinístico: o LLM não decide nada aqui, só lê a lista de mudanças (ferramenta da T23e).
Limite conhecido, o mesmo da v1: só entram o corpo da requisição e o das respostas 2xx; parâmetros
de caminho e de consulta ficam de fora.
"""
import json
from dataclasses import dataclass
from pathlib import Path

REQUISICAO = "requisicao"
RESPOSTA = "resposta"
METODOS_HTTP = ("get", "post", "put", "patch", "delete")

REMOCAO = "remocao"
CAMPO_OBRIGATORIO_NOVO = "campo_obrigatorio_novo"


@dataclass(frozen=True)
class Propriedade:
    """Um campo do contrato depois de achatado: tipo, formato, valores permitidos e se é obrigatório."""
    tipo: str
    formato: str | None
    enum: tuple[str, ...] | None
    obrigatoria: bool



@dataclass(frozen=True)
class Mudanca:
    """Uma mudança de contrato num campo de uma operação (método, rota e lado)."""
    tipo: str
    metodo: str
    rota: str
    lado: str
    caminho: str
    novo_caminho: str | None = None  # só na renomeação
    antes: Propriedade | None = None
    depois: Propriedade | None = None


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


def _schema_do_conteudo(conteudo: dict) -> dict | None:
    """O schema do primeiro tipo de mídia que tiver um (na API cobaia, `application/json`)."""
    for midia in conteudo.values():
        if "schema" in midia:
            return midia["schema"]
    return None


def achatar(contrato: dict) -> dict[tuple[str, str, str], dict[str, Propriedade]]:
    """Mapeia (método, rota, lado) para a planilha de campos; o lado é a requisição ou a resposta 2xx."""
    planilhas = {}
    for rota, operacoes in contrato.get("paths", {}).items():
        for metodo in METODOS_HTTP:
            operacao = operacoes.get(metodo)
            if operacao is None:
                continue
            corpo = _schema_do_conteudo(operacao.get("requestBody", {}).get("content", {}))
            if corpo is not None:
                planilhas[(metodo.upper(), rota, REQUISICAO)] = achatar_schema(contrato, corpo)
            for status, resposta in operacao.get("responses", {}).items():
                schema = _schema_do_conteudo(resposta.get("content", {}))
                if status.startswith("2") and schema is not None:
                    planilhas[(metodo.upper(), rota, RESPOSTA)] = achatar_schema(contrato, schema)
    return planilhas


def _debaixo_de(caminho: str, raizes: set[str]) -> bool:
    """Se o campo é filho ou neto de algum dos caminhos; `itens[]` também é filho de `itens`."""
    return any(caminho.startswith(r + ".") or caminho.startswith(r + "[]") for r in raizes)


def diferenca(antigo: dict, novo: dict) -> list[Mudanca]:
    """Lista as mudanças de contrato nas operações que existem nos dois, na ordem (método, rota, lado, caminho)."""
    planilhas_antigas, planilhas_novas = achatar(antigo), achatar(novo)
    mudancas = []
    for chave in sorted(planilhas_antigas.keys() & planilhas_novas.keys()):
        velhos, novos = planilhas_antigas[chave], planilhas_novas[chave]
        removidos = {c for c in velhos if c not in novos}
        adicionados = {c for c in novos if c not in velhos}
        # o filho de um campo que sumiu ou apareceu acompanha o pai e não vira mudança à parte
        for c in sorted(c for c in removidos if not _debaixo_de(c, removidos)):
            mudancas.append(Mudanca(REMOCAO, *chave, c, antes=velhos[c]))
        for c in sorted(c for c in adicionados if not _debaixo_de(c, adicionados)):
            if novos[c].obrigatoria:  # um campo opcional novo não quebra o teste
                mudancas.append(Mudanca(CAMPO_OBRIGATORIO_NOVO, *chave, c, depois=novos[c]))
    return mudancas
