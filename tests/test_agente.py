import unittest

from agente_contrato.agentes import LIMITE_TOTAL, rodar_agente
from agente_contrato.execucao import Falha
from agente_contrato.laco import RespostaModelo
from agente_contrato.prompts import carregar
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaDupla, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

DIFERENCA = "- GET /produtos, resposta 200: o campo nome foi renomeado para titulo"
LEGITIMA = RespostaModelo('{"rotulo": "legitima", "justificativa": "O campo nome virou titulo."}')
PROBLEMA = RespostaModelo('{"rotulo": "problema_real", "justificativa": "O código não segue o contrato."}')
FALHA = Falha("failure", "java.lang.AssertionError", "No value at JSON path \"$.nome\"")


class TestRodarAgente(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas(ver_diferenca=DIFERENCA)
        self.relogio = RelogioCaso(agora=RelogioFalso())

    def rodar(self, roteiro_classifier, roteiro_repair=()):
        fabrica = FabricaDupla(list(roteiro_classifier), list(roteiro_repair))
        r = rodar_agente(fabrica, self.ferramentas.dicionario(), self.relogio, "src/test/java/loja/ProdutoTest.java",
                         "ProdutoTest", "lista", FALHA, "@Test\nvoid lista() {}")
        return fabrica, r

    def test_rotulo_legitimo_o_repair_roda_com_o_diagnostico_e_a_diferenca(self):  # D62, D125
        fabrica, r = self.rodar([pede("c1", "ver_diferenca"), LEGITIMA],
                                [pede("r1", "salvar_reparo", metodo_reparado="void lista() {}"),
                                 RespostaModelo("Troquei nome por titulo.")])
        self.assertEqual((r.motivo, r.classifier.rotulo, r.chamadas), ("reparo", "legitima", 4))
        self.assertEqual(fabrica.sistemas, [carregar("classifier"), carregar("repair")])
        primeira_do_repair = fabrica.modelos[1].recebidos[0][0]
        self.assertIn("Rótulo: legitima\nJustificativa: O campo nome virou titulo.", primeira_do_repair)
        self.assertIn(DIFERENCA, primeira_do_repair)

    def test_problema_real_o_repair_nao_roda(self):  # D62
        fabrica, r = self.rodar([PROBLEMA])
        self.assertEqual((r.motivo, r.classifier.rotulo, r.repair), ("nao_reparar", "problema_real", None))
        self.assertEqual(fabrica.sistemas, [carregar("classifier")])  # o modelo do Repair nem é criado
        self.assertNotIn("salvar_reparo", self.ferramentas.rodadas)

    def test_estouro_do_classifier_o_repair_nao_roda(self):  # D62: sem rótulo é falha com o motivo
        fabrica, r = self.rodar([pede(f"c{i}", "rodar_teste") for i in range(5)])
        self.assertEqual((r.motivo, r.repair, r.chamadas), ("classifier_limite_de_chamadas", None, 4))
        self.assertEqual(len(fabrica.sistemas), 1)

    def test_saida_invalida_do_classifier_o_repair_nao_roda(self):  # D102
        _, r = self.rodar([RespostaModelo("É legítima.")])
        self.assertEqual((r.motivo, r.repair), ("saida_invalida", None))

    def test_estouro_do_repair(self):  # D62
        _, r = self.rodar([LEGITIMA], [pede(f"r{i}", "ler_arquivo", caminho="src") for i in range(7)])
        self.assertEqual((r.motivo, r.repair.laco.chamadas), ("repair_limite_de_chamadas", 6))

    def test_os_dois_no_limite_nao_passam_de_10(self):  # D62
        classifier = [pede(f"c{i}", "ler_arquivo", caminho="src") for i in range(3)] + [LEGITIMA]
        _, r = self.rodar(classifier, [pede(f"r{i}", "rodar_teste") for i in range(7)])
        self.assertEqual((r.classifier.laco.chamadas, r.repair.laco.chamadas, r.chamadas), (4, 6, LIMITE_TOTAL))


if __name__ == "__main__":
    unittest.main()
