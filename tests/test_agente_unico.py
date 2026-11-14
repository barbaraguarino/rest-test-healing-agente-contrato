"""Testes do agente único (T49, D67): um laço só, 4 ferramentas, até 10 chamadas. LLM simulado."""
import unittest

from agente_contrato.agentes import (FERRAMENTAS_AGENTE_UNICO, LIMITE_AGENTE_UNICO, LIMITE_TOTAL, SCHEMA_CLASSIFIER,
                                     rodar_agente_unico)
from agente_contrato.execucao import Falha
from agente_contrato.ferramentas import RECUSA_DO_GUARDA
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.prompts import carregar
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaSimulada, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

DIFERENCA = "- GET /produtos, resposta 200: o campo nome foi renomeado para titulo"
LEGITIMA = RespostaModelo('{"rotulo": "legitima", "justificativa": "O campo nome virou titulo; troquei no teste."}')
PROBLEMA = RespostaModelo('{"rotulo": "problema_real", "justificativa": "O código não segue o contrato."}')
FALHA = Falha("failure", "java.lang.AssertionError", "No value at JSON path \"$.nome\"")
SALVA = pede("s1", "salvar_reparo", metodo_reparado="void lista() {}")


class TestAgenteUnico(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas(ver_diferenca=DIFERENCA)
        self.relogio = RelogioCaso(agora=RelogioFalso())

    def rodar(self, *roteiro):
        fabrica = FabricaSimulada(*roteiro)
        r = rodar_agente_unico(fabrica, self.ferramentas.dicionario(), self.relogio,
                               "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", FALHA,
                               "@Test\nvoid lista() {}")
        return fabrica, r

    def test_um_laco_com_as_4_ferramentas_o_prompt_proprio_e_o_schema(self):  # D67, D131
        fabrica, _ = self.rodar(PROBLEMA)
        self.assertEqual(fabrica.sistema, carregar("agente_unico"))
        self.assertEqual([d["name"] for d in fabrica.definicoes], list(FERRAMENTAS_AGENTE_UNICO))
        self.assertEqual(fabrica.formato, SCHEMA_CLASSIFIER)
        self.assertEqual(LIMITE_AGENTE_UNICO, LIMITE_TOTAL)

    def test_a_primeira_mensagem_e_a_do_classifier_sem_a_diferenca(self):  # ele busca com ver_diferenca
        fabrica, _ = self.rodar(PROBLEMA)
        primeira = fabrica.modelo.recebidos[0][0]
        self.assertIn("ProdutoTest.lista", primeira)
        self.assertNotIn(DIFERENCA, primeira)
        self.assertNotIn("Diagnóstico", primeira)

    def test_classifica_e_repara_no_mesmo_laco(self):
        _, r = self.rodar(pede("c1", "ver_diferenca"), SALVA, pede("t1", "rodar_teste"), LEGITIMA)
        self.assertEqual((r.motivo, r.rotulo, r.reparou, r.chamadas, r.incoerente),
                         ("reparo", "legitima", True, 4, False))
        self.assertEqual(self.ferramentas.rodadas, ["ver_diferenca", "salvar_reparo", "rodar_teste"])

    def test_problema_real_sem_reparo(self):
        _, r = self.rodar(pede("c1", "ver_diferenca"), PROBLEMA)
        self.assertEqual((r.motivo, r.rotulo, r.reparou), ("nao_reparar", "problema_real", False))

    def test_problema_real_com_reparo_vale_o_arquivo_e_fica_marcado(self):  # decisão B da T49
        _, r = self.rodar(SALVA, PROBLEMA)
        self.assertEqual((r.motivo, r.reparou, r.incoerente), ("reparo", True, True))

    def test_legitima_sem_reparo(self):
        _, r = self.rodar(LEGITIMA)
        self.assertEqual((r.motivo, r.reparou), ("sem_reparo", False))

    def test_limite_de_10_sem_reparo(self):  # D67
        _, r = self.rodar(*[pede(f"c{i}", "ler_arquivo", caminho="src") for i in range(11)])
        self.assertEqual((r.motivo, r.chamadas, r.reparou), ("limite_de_chamadas", 10, False))

    def test_limite_depois_do_reparo_vale_o_reparo(self):  # como no Repair (T23f)
        _, r = self.rodar(SALVA, *[pede(f"t{i}", "rodar_teste") for i in range(10)])
        self.assertEqual((r.motivo, r.chamadas, r.reparou), ("reparo", 10, True))

    def test_saida_invalida_sem_reparo(self):  # D102
        _, r = self.rodar(RespostaModelo("É legítima."))
        self.assertEqual((r.motivo, r.rotulo, r.reparou), ("saida_invalida", None, False))
        self.assertIn("JSON", r.detalhe)

    def test_saida_invalida_depois_do_reparo(self):  # como a D132: vale o reparo aceito
        _, r = self.rodar(SALVA, RespostaModelo("Reparei o teste."))
        self.assertEqual((r.motivo, r.reparou), ("reparo_saida_invalida", True))

    def test_reparo_recusado_pelo_guarda_nao_conta(self):  # D129
        self.ferramentas.respostas["salvar_reparo"] = ErroDeFerramenta(f"{RECUSA_DO_GUARDA}: menos asserções")
        _, r = self.rodar(SALVA, LEGITIMA)
        self.assertEqual((r.motivo, r.reparou), ("sem_reparo", False))

    def test_tempo_do_caso_esgotado(self):  # D111d
        relogio = RelogioFalso()
        self.relogio = RelogioCaso(10, agora=relogio)
        self.ferramentas.respostas["rodar_teste"] = lambda: relogio.andar(11) or "O teste falhou."
        _, r = self.rodar(pede("t1", "rodar_teste"), LEGITIMA)
        self.assertEqual((r.motivo, r.chamadas), ("limite_do_caso", 1))


if __name__ == "__main__":
    unittest.main()
