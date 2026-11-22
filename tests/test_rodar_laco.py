import unittest

from agente_contrato.laco import (ErroDeFerramenta, PedidoFerramenta, RespostaModelo, ResultadoFerramenta,
                                  rodar_laco)
from agente_contrato.relogio import RelogioCaso
from tests.relogio_falso import RelogioFalso


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

    def test_ferramenta_desconhecida_volta_ao_modelo_como_erro(self):
        pede_inexistente = RespostaModelo("vou ler", (PedidoFerramenta("p1", "ler_arquivo", {}),))
        modelo = ModeloSimulado(pede_inexistente, RespostaModelo("rótulo: contrato"))
        r = rodar_laco(modelo, "o teste falhou", self.ferramentas(), max_chamadas=4)
        self.assertEqual((r.motivo, r.chamadas), ("terminou", 2))  # o laço segue, sem KeyError
        (resultado,) = modelo.recebidos[1][-1]
        self.assertEqual((resultado.id_pedido, resultado.erro), ("p1", True))
        self.assertIn("ler_arquivo", resultado.conteudo)
        self.assertIn("rodar_teste", resultado.conteudo)  # o modelo fica sabendo o que existe

    def test_pedido_desconhecido_nao_impede_os_outros_da_mesma_resposta(self):
        pedidos = (PedidoFerramenta("p1", "ler_arquivo", {}), PedidoFerramenta("p2", "rodar_teste", {}))
        modelo = ModeloSimulado(RespostaModelo("duas coisas", pedidos), RespostaModelo("fim"))
        rodar_laco(modelo, "o teste falhou", self.ferramentas(), max_chamadas=4)
        erro, ok = modelo.recebidos[1][-1]
        self.assertEqual((erro.erro, ok), (True, ResultadoFerramenta("p2", "falhou")))
        self.assertEqual(self.execucoes, 1)

    def test_erro_de_ferramenta_volta_ao_modelo_e_o_laco_segue(self):
        def recusa(entrada: dict) -> str:
            raise ErroDeFerramenta("caminho fora das pastas permitidas")
        modelo = ModeloSimulado(pede_teste("p1"), RespostaModelo("fim"))
        r = rodar_laco(modelo, "o teste falhou", {"rodar_teste": recusa}, max_chamadas=4)
        self.assertEqual(r.motivo, "terminou")
        self.assertEqual(modelo.recebidos[1][-1],
                         (ResultadoFerramenta("p1", "caminho fora das pastas permitidas", erro=True),))

    def test_outro_erro_nao_e_do_modelo_e_para_o_caso(self):
        def quebra(entrada: dict) -> str:
            raise RuntimeError("o Maven executou 2 testes")
        modelo = ModeloSimulado(pede_teste("p1"), RespostaModelo("fim"))
        with self.assertRaises(RuntimeError):
            rodar_laco(modelo, "o teste falhou", {"rodar_teste": quebra}, max_chamadas=4)



class TestLacoComRelogio(unittest.TestCase):
    """O relógio do caso (D111(b)): o tempo das ferramentas conta, a espera do LLM não."""

    def setUp(self):
        self.tempo = RelogioFalso()
        self.relogio = RelogioCaso(180, agora=self.tempo)

    def ferramenta_de_100s(self, entrada: dict) -> str:
        self.tempo.andar(100)
        return "falhou"

    def modelo_lento(self, *roteiro: RespostaModelo):
        """LLM simulado que demora 1000 s em cada resposta."""
        simulado = ModeloSimulado(*roteiro)

        def responder(historico):
            self.tempo.andar(1000)
            return simulado(historico)
        responder.simulado = simulado
        return responder

    def test_espera_do_llm_nao_estoura_o_caso(self):
        modelo = self.modelo_lento(RespostaModelo("rótulo: contrato"))
        r = rodar_laco(modelo, "o teste falhou", {}, max_chamadas=4, relogio=self.relogio)
        self.assertEqual(r.motivo, "terminou")
        self.assertEqual(self.relogio.gasto(), 0)

    def test_estouro_do_caso_para_antes_de_chamar_o_modelo_de_novo(self):
        modelo = self.modelo_lento(pede_teste("p1"), pede_teste("p2"), RespostaModelo("fim"))
        r = rodar_laco(modelo, "o teste falhou", {"rodar_teste": self.ferramenta_de_100s},
                       max_chamadas=6, relogio=self.relogio)
        # 100 s + 100 s de ferramenta passam dos 180 s: a terceira resposta nunca é pedida
        self.assertEqual((r.motivo, r.chamadas, r.texto_final), ("limite_do_caso", 2, None))
        self.assertEqual(len(modelo.simulado.recebidos), 2)


if __name__ == "__main__":
    unittest.main()
