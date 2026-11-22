import unittest

from agente_contrato.agentes import SCHEMA_CLASSIFIER, SaidaInvalida, ler_rotulo, rodar_classifier
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.prompts import carregar
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaSimulada, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

ROTULO_LEGITIMA = '{"rotulo": "legitima", "justificativa": "O campo nome virou titulo no contrato."}'


class TestLerRotulo(unittest.TestCase):
    def test_json_valido(self):
        self.assertEqual(ler_rotulo(ROTULO_LEGITIMA), ("legitima", "O campo nome virou titulo no contrato."))

    def test_texto_que_nao_e_json(self):
        with self.assertRaisesRegex(SaidaInvalida, "JSON ilegível"):
            ler_rotulo("O rótulo é legitima.")

    def test_rotulo_fora_dos_dois(self):
        with self.assertRaisesRegex(SaidaInvalida, "rótulo fora"):
            ler_rotulo('{"rotulo": "regressao", "justificativa": "x"}')

    def test_campo_a_mais_ou_a_menos(self):
        with self.assertRaisesRegex(SaidaInvalida, "campos"):
            ler_rotulo('{"rotulo": "legitima"}')

    def test_justificativa_vazia(self):
        with self.assertRaisesRegex(SaidaInvalida, "justificativa vazia"):
            ler_rotulo('{"rotulo": "legitima", "justificativa": "  "}')


class TestRodarClassifier(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas()
        self.relogio = RelogioCaso(agora=RelogioFalso())

    def rodar(self, *roteiro: RespostaModelo):
        fabrica = FabricaSimulada(*roteiro)
        return fabrica, rodar_classifier(fabrica, "o teste falhou", self.ferramentas.dicionario(), self.relogio)

    def test_recebe_o_prompt_e_so_as_ferramentas_de_leitura(self):  # D62, D125
        fabrica, _ = self.rodar(RespostaModelo(ROTULO_LEGITIMA))
        self.assertEqual(fabrica.sistema, carregar("classifier"))
        self.assertEqual([d["name"] for d in fabrica.definicoes], ["ler_arquivo", "ver_diferenca", "rodar_teste"])

    def test_manda_o_schema_do_rotulo(self):  # D131
        fabrica, _ = self.rodar(RespostaModelo(ROTULO_LEGITIMA))
        self.assertEqual(fabrica.formato, SCHEMA_CLASSIFIER)
        self.assertEqual(fabrica.formato["properties"]["rotulo"]["enum"], ["legitima", "problema_real"])

    def test_investiga_e_entrega_o_rotulo(self):
        _, r = self.rodar(pede("p1", "ver_diferenca"), pede("p2", "ler_arquivo", caminho="src/main"),
                          RespostaModelo(ROTULO_LEGITIMA))
        self.assertEqual((r.motivo, r.rotulo, r.laco.chamadas), ("rotulo", "legitima", 3))
        self.assertEqual(self.ferramentas.rodadas, ["ver_diferenca", "ler_arquivo"])

    def test_pedido_de_salvar_reparo_e_recusado_e_nada_e_salvo(self):  # D62: o Classifier só lê
        fabrica, r = self.rodar(pede("p1", "salvar_reparo", metodo_reparado="void lista() {}"),
                                RespostaModelo(ROTULO_LEGITIMA))
        (resultado,) = fabrica.modelo.recebidos[1][-1]
        self.assertTrue(resultado.erro)
        self.assertNotIn("salvar_reparo", self.ferramentas.rodadas)
        self.assertEqual(r.motivo, "rotulo")

    def test_erro_de_ferramenta_volta_ao_modelo_e_ele_segue(self):  # D124
        self.ferramentas.respostas["ler_arquivo"] = ErroDeFerramenta("Leitura não permitida: README.md.")
        fabrica, r = self.rodar(pede("p1", "ler_arquivo", caminho="README.md"), RespostaModelo(ROTULO_LEGITIMA))
        (resultado,) = fabrica.modelo.recebidos[1][-1]
        self.assertEqual((resultado.erro, resultado.conteudo), (True, "Leitura não permitida: README.md."))
        self.assertEqual(r.motivo, "rotulo")

    def test_estouro_do_limite_sem_rotulo(self):  # D62: falha registrada com o motivo
        fabrica, r = self.rodar(*(pede(f"p{i}", "rodar_teste") for i in range(5)))
        self.assertEqual((r.motivo, r.rotulo, r.laco.chamadas), ("classifier_limite_de_chamadas", None, 4))
        self.assertEqual(len(fabrica.modelo.recebidos), 4)  # a quinta resposta nunca é pedida

    def test_resposta_final_invalida(self):  # D102
        _, r = self.rodar(RespostaModelo("Acho que é legitima."))
        self.assertEqual((r.motivo, r.rotulo), ("saida_invalida", None))
        self.assertIn("JSON ilegível", r.detalhe)

    def test_tempo_do_caso_acabou(self):  # D111b: só as ferramentas gastam o relógio do caso
        agora = RelogioFalso()
        self.relogio = RelogioCaso(agora=agora)

        def teste_lento() -> str:
            agora.andar(200)  # passa dos 180 s do caso
            return "O teste falhou."
        self.ferramentas.respostas["rodar_teste"] = teste_lento
        _, r = self.rodar(pede("p1", "rodar_teste"), RespostaModelo(ROTULO_LEGITIMA))
        self.assertEqual((r.motivo, r.rotulo, r.laco.chamadas), ("limite_do_caso", None, 1))

if __name__ == "__main__":
    unittest.main()
