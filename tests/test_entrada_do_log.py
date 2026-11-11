import unittest

from agente_contrato.agentes import rodar_agente
from agente_contrato.laco import RespostaModelo
from agente_contrato.registro import entrada_do_log, traduzir
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaDupla, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso
from tests.test_traduzir import FALHA, LEGITIMA, RECUSA, salva


class TestEntradaDoLog(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas()

    def entrada(self, roteiro_classifier, roteiro_repair=()):
        fabrica = FabricaDupla(list(roteiro_classifier), list(roteiro_repair))
        agente = rodar_agente(fabrica, self.ferramentas.dicionario(), RelogioCaso(agora=RelogioFalso()),
                              "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", FALHA,
                              "@Test\nvoid lista() {}")
        return entrada_do_log("A1-001", 2, agente, traduzir(agente), "abc123", "def456+alterado")

    def test_guarda_o_porque_e_os_commits(self):  # D105
        self.ferramentas.respostas["salvar_reparo"] = RECUSA
        e = self.entrada([pede("c1", "ver_diferenca"), LEGITIMA], [salva("r1"), RespostaModelo("Desisto.")])
        self.assertEqual(e, {
            "id_caso": "A1-001", "repeticao": 2, "motivo": "repair_sem_reparo",
            "decisao": "nao_reparar", "erro": "guarda",
            "rotulo_classifier": "legitima", "justificativa": "O campo nome virou titulo.", "detalhe": None,
            "chamadas_classifier": 2, "chamadas_repair": 2, "recusas_do_guarda": [str(RECUSA)],
            "commit_do_prompt": "abc123", "commit_do_codigo": "def456+alterado"})

    def test_saida_invalida_leva_o_detalhe_e_o_repair_nao_rodou(self):
        e = self.entrada([RespostaModelo("não sei")])
        self.assertEqual((e["erro"], e["chamadas_repair"], e["recusas_do_guarda"]), ("saida_invalida", 0, []))
        self.assertIn("JSON ilegível", e["detalhe"])
