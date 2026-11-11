import unittest

from agente_contrato.agentes import rodar_repair
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.prompts import carregar
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaSimulada, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

REPARO = "@Test\nvoid lista() {\n    novo();\n}"


def salva(id_pedido: str) -> RespostaModelo:
    return pede(id_pedido, "salvar_reparo", metodo_reparado=REPARO)


class TestRodarRepair(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas()
        self.relogio = RelogioCaso(agora=RelogioFalso())

    def rodar(self, *roteiro: RespostaModelo):
        fabrica = FabricaSimulada(*roteiro)
        return fabrica, rodar_repair(fabrica, "repare o teste", self.ferramentas.dicionario(), self.relogio)

    def test_recebe_o_prompt_e_as_ferramentas_sem_ver_diferenca(self):  # D62, D125
        fabrica, _ = self.rodar(RespostaModelo("nada a fazer"))
        self.assertEqual(fabrica.sistema, carregar("repair"))
        self.assertEqual([d["name"] for d in fabrica.definicoes], ["ler_arquivo", "rodar_teste", "salvar_reparo"])

    def test_salva_confere_e_termina(self):
        self.ferramentas.respostas["rodar_teste"] = "O teste passou."
        _, r = self.rodar(salva("p1"), pede("p2", "rodar_teste"), RespostaModelo("Renomeei nome para titulo."))
        self.assertEqual((r.motivo, r.laco.chamadas), ("reparo", 3))
        self.assertEqual(self.ferramentas.rodadas, ["salvar_reparo", "rodar_teste"])

    def test_pedido_de_ver_diferenca_e_recusado(self):  # D125
        fabrica, _ = self.rodar(pede("p1", "ver_diferenca"), RespostaModelo("fim"))
        (resultado,) = fabrica.modelo.recebidos[1][-1]
        self.assertTrue(resultado.erro)
        self.assertNotIn("ver_diferenca", self.ferramentas.rodadas)

    def test_terminar_sem_salvar_e_falha(self):
        _, r = self.rodar(pede("p1", "ler_arquivo", caminho="src/main"), RespostaModelo("Não sei reparar."))
        self.assertEqual(r.motivo, "repair_sem_reparo")

    def test_salvamento_recusado_nao_conta_como_reparo(self):  # D124: o erro volta ao modelo
        self.ferramentas.respostas["salvar_reparo"] = ErroDeFerramenta("O reparo não foi salvo: método não achado.")
        fabrica, r = self.rodar(salva("p1"), RespostaModelo("Desisto."))
        (resultado,) = fabrica.modelo.recebidos[1][-1]
        self.assertEqual((resultado.erro, resultado.conteudo), (True, "O reparo não foi salvo: método não achado."))
        self.assertEqual(r.motivo, "repair_sem_reparo")

    def test_estouro_do_limite_sem_reparo(self):  # D62: falha registrada com o motivo
        fabrica, r = self.rodar(*(pede(f"p{i}", "ler_arquivo", caminho="src") for i in range(7)))
        self.assertEqual((r.motivo, r.laco.chamadas), ("repair_limite_de_chamadas", 6))
        self.assertEqual(len(fabrica.modelo.recebidos), 6)

    def test_estouro_do_limite_depois_de_salvar_conta_como_reparo(self):  # o Maven final é quem julga
        _, r = self.rodar(salva("p1"), *(pede(f"p{i}", "rodar_teste") for i in range(2, 8)))
        self.assertEqual((r.motivo, r.laco.chamadas, r.laco.motivo), ("reparo", 6, "limite_de_chamadas"))

    def test_limite_menor_vindo_do_total(self):  # D62: o total de 10 pode cortar o Repair
        fabrica = FabricaSimulada(*(pede(f"p{i}", "rodar_teste") for i in range(7)))
        r = rodar_repair(fabrica, "repare", self.ferramentas.dicionario(), self.relogio, max_chamadas=2)
        self.assertEqual((r.motivo, r.laco.chamadas), ("repair_limite_de_chamadas", 2))


if __name__ == "__main__":
    unittest.main()
