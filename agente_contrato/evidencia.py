"""Montagem da evidência que o Classifier e o Repair recebem (D100).

É código determinístico: o LLM só vê o que este módulo escolhe. Entram a diferença de
contrato (a mesma da baseline), a mensagem de falha, o método de teste afetado e os
arquivos de `src/main` do módulo do teste. Nunca entra nada de `casos/` nem do oráculo
(CLAUDE.md do repositório; D73).
"""

import re
from pathlib import Path

from . import contrato as c
from . import execucao
from . import teste_java as tj
from .leitura_falha import Falha


def _tipo(p: c.Propriedade | None) -> str:
    if p is None:
        return "?"
    texto = p.tipo + (f" ({p.formato})" if p.formato else "")
    return texto + (f", valores {list(p.enum)}" if p.enum else "")


def descrever_mudanca(m: c.Mudanca) -> str:
    onde = f"{m.metodo} {m.rota}, {m.lado}"
    if m.tipo == c.RENOMEACAO:
        return f'{onde}: o campo "{m.caminho}" foi renomeado para "{m.novo_caminho}" ({_tipo(m.depois)})'
    if m.tipo == c.REMOCAO:
        return f'{onde}: o campo "{m.caminho}" foi removido ({_tipo(m.antes)})'
    if m.tipo == c.ALTERACAO_TIPO:
        return f'{onde}: o campo "{m.caminho}" mudou de {_tipo(m.antes)} para {_tipo(m.depois)}'
    if m.tipo == c.CAMPO_OBRIGATORIO_NOVO:
        return f'{onde}: o campo "{m.caminho}" passou a ser obrigatório ({_tipo(m.depois)})'
    raise ValueError(f"tipo de mudança desconhecido: {m.tipo}")


def descrever_mudancas(mudancas: list[c.Mudanca]) -> str:
    if not mudancas:
        return "O contrato não registra nenhuma diferença entre o OpenAPI antigo e o novo."
    return "\n".join(f"- {descrever_mudanca(m)}" for m in mudancas)


def _inicio_da_linha(texto: str, i: int) -> int:
    return texto.rfind("\n", 0, i) + 1


def texto_do_metodo(texto: str, nome: str) -> str:
    """O método inteiro: anotações (`@Test`, `@DisplayName`...), assinatura e corpo."""
    m = tj.localizar_metodo(texto, nome)  # garante uma única ocorrência
    assinatura = re.search(rf"\bvoid\s+{re.escape(nome)}\s*\(", texto)
    inicio = _inicio_da_linha(texto, assinatura.start())
    while inicio > 0:  # sobe enquanto a linha de cima for uma anotação
        anterior = _inicio_da_linha(texto, inicio - 1)
        if not texto[anterior:inicio].lstrip().startswith("@"):
            break
        inicio = anterior
    return texto[inicio:m.fim]


def arquivos_do_modulo(raiz: Path, arquivo_de_teste: Path) -> dict[str, str]:
    """Arquivos `.java` de `src/main` no pacote do teste (e nos subpacotes, como `dto/`).

    O pacote vem do caminho do teste: `.../produto/ProdutoControllerTest.java` leva
    `src/main/java/.../produto/`. A classe de teste inteira não entra (só o método, D100-c).
    A chave é o caminho relativo à raiz da API.
    """
    pacote = arquivo_de_teste.parent.relative_to(raiz / "src" / "test" / "java")
    pasta = raiz / "src" / "main" / "java" / pacote
    if not pasta.is_dir():
        raise execucao.ErroDeExecucao(f"módulo do teste não encontrado em src/main: {pacote}")
    return {str(a.relative_to(raiz)): a.read_text(encoding="utf-8") for a in sorted(pasta.rglob("*.java"))}


def montar(mudancas: list[c.Mudanca], falha: Falha | None, classe: str, metodo: str,
           texto_do_teste: str, modulo: dict[str, str]) -> str:
    """Texto da evidência, igual para os dois agentes; as instruções ficam em `prompts/`."""
    if falha is None:  # sem relatório: o teste nem compilou
        sobre_falha = "O teste não compilou; o Maven não gerou mensagem de falha."
    else:
        sobre_falha = f"Tipo: {falha.tipo} ({falha.excecao})\nMensagem: {falha.mensagem}"
    partes = [
        "## Diferenças entre o contrato OpenAPI antigo e o novo",
        descrever_mudancas(mudancas),
        f"## Falha do teste {classe}.{metodo}",
        sobre_falha,
        "## Método de teste (conteúdo atual)",
        f"```java\n{texto_do_metodo(texto_do_teste, metodo)}\n```",
        "## Código do módulo (src/main)",
    ]
    partes += [f"### {caminho}\n```java\n{conteudo.rstrip()}\n```" for caminho, conteudo in modulo.items()]
    return "\n\n".join(partes) + "\n"
