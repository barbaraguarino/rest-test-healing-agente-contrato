"""Dublês do LLM para os testes do Classifier e do Repair: nenhum teste chama a API paga."""
from agente_contrato.laco import PedidoFerramenta, RespostaModelo
from tests.test_rodar_laco import ModeloSimulado


class FabricaSimulada:
    """Faz o papel do `criar_modelo`: guarda o prompt de sistema e as definições que cada agente mandou."""

    def __init__(self, *roteiro: RespostaModelo):
        self.modelo = ModeloSimulado(*roteiro)
        self.sistema = None
        self.definicoes = None
        self.formato = None

    def __call__(self, sistema: str, definicoes: list[dict], formato: dict | None = None) -> ModeloSimulado:
        self.sistema, self.definicoes, self.formato = sistema, definicoes, formato
        return self.modelo


def pede(id_pedido: str, nome: str, **entrada) -> RespostaModelo:
    """Uma resposta do modelo com um só pedido de ferramenta."""
    return RespostaModelo(f"vou usar {nome}", (PedidoFerramenta(id_pedido, nome, entrada),))


class FerramentasFalsas:
    """As quatro ferramentas do `montar`; guarda o nome de cada uma que rodou.

    Cada resposta é um texto, uma exceção (que a ferramenta levanta) ou uma função sem argumentos.
    """

    def __init__(self, **respostas):
        self.rodadas = []
        self.respostas = {"ler_arquivo": "class Produto {}", "ver_diferenca": "- campo nome renomeado",
                          "rodar_teste": "O teste falhou.", "salvar_reparo": "Reparo salvo.", **respostas}

    def dicionario(self) -> dict:
        return {nome: self._funcao(nome) for nome in self.respostas}

    def _funcao(self, nome: str):
        def executar(entrada: dict) -> str:
            self.rodadas.append(nome)
            resposta = self.respostas[nome]
            if isinstance(resposta, Exception):
                raise resposta
            return resposta() if callable(resposta) else resposta
        return executar


class FabricaDupla:
    """Faz o papel do `criar_modelo` no agente inteiro: o primeiro modelo criado é o Classifier, o segundo o Repair."""

    def __init__(self, roteiro_classifier: list[RespostaModelo], roteiro_repair: list[RespostaModelo]):
        self.modelos = [ModeloSimulado(*roteiro_classifier), ModeloSimulado(*roteiro_repair)]
        self.sistemas = []  # o prompt de sistema de cada modelo criado, em ordem
        self.formatos = []  # o formato (D131) de cada modelo criado, em ordem

    def __call__(self, sistema: str, definicoes: list[dict], formato: dict | None = None) -> ModeloSimulado:
        self.sistemas.append(sistema)
        self.formatos.append(formato)
        return self.modelos[len(self.sistemas) - 1]
