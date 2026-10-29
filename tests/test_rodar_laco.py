import unittest

from agente_contrato.laco import PedidoFerramenta, RespostaModelo, ResultadoFerramenta, rodar_laco


class ModeloSimulado:
    """LLM simulado: devolve as respostas de um roteiro, em ordem, e guarda o que recebeu."""

    def __init__(self, *roteiro: RespostaModelo):
        self.roteiro = list(roteiro)
        self.recebidos = []

    def __call__(self, historico: list) -> RespostaModelo:
        self.recebidos.append(list(historico))
        return self.roteiro.pop(0)


def pede_teste(id_pedido: str) -> RespostaModelo:
    return RespostaModelo("vou rodar o teste", (PedidoFerramenta(id_pedido, "rodar_teste", {}),))


class TestRodarLaco(unittest.TestCase):
    def setUp(self):
        self.execucoes = 0

    def rodar_teste_falso(self, entrada: dict) -> str:
        self.execucoes += 1
        return "falhou"

    def ferramentas(self) -> dict:
        return {"rodar_teste": self.rodar_teste_falso}

    def test_modelo_que_termina_de_cara_nao_executa_nada(self):
        modelo = ModeloSimulado(RespostaModelo("rótulo: contrato"))
        r = rodar_laco(modelo, "o teste falhou", self.ferramentas(), max_chamadas=4)
        self.assertEqual((r.motivo, r.chamadas, r.texto_final), ("terminou", 1, "rótulo: contrato"))
        self.assertEqual(self.execucoes, 0)

    def test_ferramenta_pedida_e_executada_e_o_resultado_volta_ao_modelo(self):
        modelo = ModeloSimulado(pede_teste("p1"), RespostaModelo("rótulo: regressao"))
        r = rodar_laco(modelo, "o teste falhou", self.ferramentas(), max_chamadas=4)
        self.assertEqual((r.motivo, r.chamadas), ("terminou", 2))
        self.assertEqual(self.execucoes, 1)
        # na segunda chamada, o modelo vê a resposta dele e o resultado ligado ao pedido p1
        self.assertEqual(modelo.recebidos[1][-1], (ResultadoFerramenta("p1", "falhou"),))

    def test_limite_de_chamadas_para_o_laco(self):
        modelo = ModeloSimulado(pede_teste("p1"), pede_teste("p2"), pede_teste("p3"))
        r = rodar_laco(modelo, "o teste falhou", self.ferramentas(), max_chamadas=2)
        self.assertEqual((r.motivo, r.chamadas, r.texto_final), ("limite_de_chamadas", 2, None))
        self.assertEqual(len(modelo.recebidos), 2)  # a terceira resposta do roteiro nunca é pedida


if __name__ == "__main__":
    unittest.main()
