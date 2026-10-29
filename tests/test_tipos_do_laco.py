import unittest

from agente_contrato.laco import PedidoFerramenta, RespostaModelo, ResultadoFerramenta


class TestRespostaModelo(unittest.TestCase):
    def test_sem_pedidos_o_modelo_terminou(self):
        self.assertTrue(RespostaModelo("rótulo: contrato").terminou)

    def test_com_pedido_o_modelo_nao_terminou(self):
        pedido = PedidoFerramenta("p1", "rodar_teste", {})
        self.assertFalse(RespostaModelo("vou rodar o teste", (pedido,)).terminou)


class TestResultadoFerramenta(unittest.TestCase):
    def test_por_padrao_nao_e_erro(self):
        self.assertFalse(ResultadoFerramenta("p1", "passou").erro)


if __name__ == "__main__":
    unittest.main()
