"""Classifier e Repair do Agente 1 (T23f, D62): dois agentes com ferramentas, em sequência.

O LLM decide o que ler, quando rodar o teste, o rótulo, o reparo e quando parar. Este código decide
quais ferramentas cada um recebe, aplica os limites de chamadas, lê o rótulo, repassa-o ao Repair e
não deixa o Repair rodar quando o rótulo é `problema_real`.
"""
import json
from dataclasses import dataclass

from agente_contrato.execucao import Falha
from agente_contrato.ferramentas import DEFINICOES
from agente_contrato.laco import ResultadoLaco, rodar_laco
from agente_contrato.prompts import carregar
from agente_contrato.relogio import RelogioCaso

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


class SaidaInvalida(ValueError):
    """A resposta final não serve (D102); a mensagem diz por quê e vai para o log."""


def ler_rotulo(texto: str) -> tuple[str, str]:
    """O rótulo e a justificativa da resposta final do Classifier, que deve ser só o JSON pedido no prompt."""
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise SaidaInvalida(f"JSON ilegível: {exc.msg}") from None
    if not isinstance(dados, dict) or set(dados) != {"rotulo", "justificativa"}:
        raise SaidaInvalida("esperado um objeto com os campos rotulo e justificativa")
    rotulo, justificativa = dados["rotulo"], dados["justificativa"]
    if rotulo not in ROTULOS:
        raise SaidaInvalida(f"rótulo fora de {list(ROTULOS)}: {rotulo!r}")
    if not isinstance(justificativa, str) or not justificativa.strip():
        raise SaidaInvalida("justificativa vazia")
    return rotulo, justificativa.strip()


def _so_as(nomes: tuple[str, ...], ferramentas: dict) -> tuple[list[dict], dict]:
    """As definições (o que o modelo vê) e as funções (o que o código executa) só das ferramentas do agente."""
    definicoes = [d for d in DEFINICOES if d["name"] in nomes]
    return definicoes, {nome: ferramentas[nome] for nome in nomes}


@dataclass(frozen=True)
class ResultadoClassifier:
    rotulo: str | None        # None quando o Classifier não entregou um rótulo válido
    justificativa: str | None
    motivo: str               # "rotulo", "saida_invalida", "classifier_limite_de_chamadas" ou "limite_do_caso"
    detalhe: str | None       # por que a saída foi inválida
    laco: ResultadoLaco       # chamadas e histórico, para o registro (T23h)


def rodar_classifier(criar_modelo, mensagem: str, ferramentas: dict, relogio: RelogioCaso) -> ResultadoClassifier:
    """Roda o Classifier no laço, com só as ferramentas de leitura e até 4 chamadas (D62).

    `criar_modelo(sistema, definicoes)` devolve o modelo que o `rodar_laco` chama: na T23i, o Claude
    de verdade; nos testes, um LLM simulado. `ferramentas` é o dicionário inteiro do `montar`; o
    Classifier só recebe as dele, e um pedido de outra volta ao modelo como ferramenta desconhecida.
    """
    definicoes, suas = _so_as(FERRAMENTAS_CLASSIFIER, ferramentas)
    modelo = criar_modelo(carregar("classifier"), definicoes)
    laco = rodar_laco(modelo, mensagem, suas, LIMITE_CLASSIFIER, relogio)
    if laco.motivo == "limite_de_chamadas":
        return ResultadoClassifier(None, None, "classifier_limite_de_chamadas", None, laco)
    if laco.motivo == "limite_do_caso":
        return ResultadoClassifier(None, None, "limite_do_caso", None, laco)
    try:
        rotulo, justificativa = ler_rotulo(laco.texto_final)
    except SaidaInvalida as exc:
        return ResultadoClassifier(None, None, "saida_invalida", str(exc), laco)
    return ResultadoClassifier(rotulo, justificativa, "rotulo", None, laco)
