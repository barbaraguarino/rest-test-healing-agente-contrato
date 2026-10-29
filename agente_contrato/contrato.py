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

RENOMEACAO = "renomeacao"
REMOCAO = "remocao"
ALTERACAO_TIPO = "alteracao_tipo"
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


def _pai(caminho: str) -> str:
    """O objeto que contém o campo: `cliente` em `cliente.cep`; vazio para um campo da raiz."""
    return caminho.rsplit(".", 1)[0] if "." in caminho else ""


def _mesma_forma(a: Propriedade, b: Propriedade) -> bool:
    """Mesmo tipo e mesmo enum; o formato (int32 ou int64) não conta."""
    return a.tipo == b.tipo and a.enum == b.enum


def diferenca(antigo: dict, novo: dict) -> list[Mudanca]:
    """Lista as mudanças de contrato nas operações que existem nos dois, em ordem de (método, rota, lado).

    Em cada operação vêm primeiro os campos que saíram ou entraram, por objeto, e depois os que continuam.
    """
    planilhas_antigas, planilhas_novas = achatar(antigo), achatar(novo)
    mudancas = []
    for chave in sorted(planilhas_antigas.keys() & planilhas_novas.keys()):
        velhos, novos = planilhas_antigas[chave], planilhas_novas[chave]
        removidos = {c for c in velhos if c not in novos}
        adicionados = {c for c in novos if c not in velhos}
        # o filho de um campo que sumiu ou apareceu acompanha o pai e não vira mudança à parte
        removidos = {c for c in removidos if not _debaixo_de(c, removidos)}
        adicionados = {c for c in adicionados if not _debaixo_de(c, adicionados)}
        for pai in sorted({_pai(c) for c in removidos | adicionados}):
            saiu = sorted(c for c in removidos if _pai(c) == pai)
            entrou = sorted(c for c in adicionados if _pai(c) == pai)
            # renomeação: no mesmo objeto, um sai e um entra com a mesma forma; com mais candidatos, não adivinha
            if len(saiu) == 1 and len(entrou) == 1 and _mesma_forma(velhos[saiu[0]], novos[entrou[0]]):
                mudancas.append(Mudanca(RENOMEACAO, *chave, saiu[0], entrou[0], velhos[saiu[0]], novos[entrou[0]]))
                continue
            for c in saiu:
                mudancas.append(Mudanca(REMOCAO, *chave, c, antes=velhos[c]))
            for c in entrou:
                if novos[c].obrigatoria:  # um campo opcional novo não quebra o teste
                    mudancas.append(Mudanca(CAMPO_OBRIGATORIO_NOVO, *chave, c, depois=novos[c]))
        for c in sorted(velhos.keys() & novos.keys()):
            if not _mesma_forma(velhos[c], novos[c]):
                mudancas.append(Mudanca(ALTERACAO_TIPO, *chave, c, antes=velhos[c], depois=novos[c]))
            elif novos[c].obrigatoria and not velhos[c].obrigatoria:
                mudancas.append(Mudanca(CAMPO_OBRIGATORIO_NOVO, *chave, c, antes=velhos[c], depois=novos[c]))
    return mudancas


def _descrever_tipo(p: Propriedade) -> str:
    """`integer (int32)` ou `string, valores ['A', 'B']`: tipo, formato e enum, quando houver."""
    texto = p.tipo + (f" ({p.formato})" if p.formato else "")
    return texto + (f", valores {list(p.enum)}" if p.enum else "")


def descrever_mudanca(m: Mudanca) -> str:
    """Uma linha da evidência em português, com o mesmo texto da v1 (D100a)."""
    onde = f"{m.metodo} {m.rota}, {m.lado}"
    if m.tipo == RENOMEACAO:
        return f'{onde}: o campo "{m.caminho}" foi renomeado para "{m.novo_caminho}" ({_descrever_tipo(m.depois)})'
    if m.tipo == REMOCAO:
        return f'{onde}: o campo "{m.caminho}" foi removido ({_descrever_tipo(m.antes)})'
    if m.tipo == ALTERACAO_TIPO:
        return f'{onde}: o campo "{m.caminho}" mudou de {_descrever_tipo(m.antes)} para {_descrever_tipo(m.depois)}'
    if m.tipo == CAMPO_OBRIGATORIO_NOVO:
        return f'{onde}: o campo "{m.caminho}" passou a ser obrigatório ({_descrever_tipo(m.depois)})'
    raise ValueError(f"tipo de mudança desconhecido: {m.tipo}")


def descrever_mudancas(mudancas: list[Mudanca]) -> str:
    """A evidência que o modelo lê: uma linha por mudança, ou o aviso de que não há diferença."""
    if not mudancas:
        return "O contrato não registra nenhuma diferença entre o OpenAPI antigo e o novo."
    return "\n".join(f"- {descrever_mudanca(m)}" for m in mudancas)
