"""Classifier e Repair do Agente 1 (T23f, D62): dois agentes com ferramentas, em sequência.

O LLM decide o que ler, quando rodar o teste, o rótulo, o reparo e quando parar. Este código decide
quais ferramentas cada um recebe, aplica os limites de chamadas, lê o rótulo, repassa-o ao Repair e
não deixa o Repair rodar quando o rótulo é `problema_real`.
"""
from agente_contrato.execucao import Falha

LIMITE_CLASSIFIER = 4  # chamadas ao LLM (D62); o número também está em prompts/classifier.md
LIMITE_REPAIR = 6      # D62; também em prompts/repair.md
LIMITE_TOTAL = 10      # D62

# D62: o Classifier só lê; D125: o Repair não tem ver_diferenca, recebe a diferença no prompt inicial.
FERRAMENTAS_CLASSIFIER = ("ler_arquivo", "ver_diferenca", "rodar_teste")
FERRAMENTAS_REPAIR = ("ler_arquivo", "rodar_teste", "salvar_reparo")

LEGITIMA = "legitima"
PROBLEMA_REAL = "problema_real"
ROTULOS = (LEGITIMA, PROBLEMA_REAL)


def _sobre_a_falha(falha: Falha | None) -> str:
    if falha is None:  # sem relatório do Surefire: o teste nem compilou (texto igual ao da v1)
        return "O teste não compilou; o Maven não gerou mensagem de falha."
    return f"Tipo: {falha.tipo} ({falha.excecao})\nMensagem: {falha.mensagem}"


def _sobre_o_teste(arquivo: str, classe: str, metodo: str, falha: Falha | None, texto_do_metodo: str) -> list[str]:
    """As partes que os dois agentes recebem: onde está o teste, a falha e o método (D100b, D117b)."""
    return [
        f"## Teste afetado\n{classe}.{metodo}, no arquivo `{arquivo}`.",
        f"## Falha do teste\n{_sobre_a_falha(falha)}",
        f"## Método de teste (conteúdo atual)\n```java\n{texto_do_metodo}\n```",
    ]


def mensagem_classifier(arquivo: str, classe: str, metodo: str, falha: Falha | None,
                        texto_do_metodo: str) -> str:
    """A primeira mensagem do Classifier; a diferença do contrato ele busca com ver_diferenca (D125)."""
    return "\n\n".join(_sobre_o_teste(arquivo, classe, metodo, falha, texto_do_metodo)) + "\n"


def mensagem_repair(arquivo: str, classe: str, metodo: str, falha: Falha | None, texto_do_metodo: str,
                    diferenca: str, rotulo: str, justificativa: str) -> str:
    """A primeira mensagem do Repair: o diagnóstico (D62), a diferença no prompt (D125, texto da D122) e o teste."""
    partes = [
        f"## Diagnóstico\nRótulo: {rotulo}\nJustificativa: {justificativa}",
        f"## Diferenças entre o contrato OpenAPI antigo e o novo\n{diferenca}",
    ]
    return "\n\n".join(partes + _sobre_o_teste(arquivo, classe, metodo, falha, texto_do_metodo)) + "\n"
