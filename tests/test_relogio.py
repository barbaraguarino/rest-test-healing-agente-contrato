import unittest

from agente_contrato.relogio import RelogioCaso
from tests.relogio_falso import RelogioFalso


class TestRelogioCaso(unittest.TestCase):
    def setUp(self):
        self.tempo = RelogioFalso()
        self.relogio = RelogioCaso(180, agora=self.tempo)

    def test_tempo_do_codigo_conta(self):
        self.tempo.andar(50)
        self.assertEqual((self.relogio.gasto(), self.relogio.restante()), (50, 130))

    def test_espera_do_llm_nao_conta(self):
        self.tempo.andar(10)
        with self.relogio.esperando_llm():
            self.tempo.andar(100)
        self.tempo.andar(5)
        self.assertEqual(self.relogio.gasto(), 15)

    def test_estoura_ao_chegar_no_limite_e_restante_nao_fica_negativo(self):
        self.tempo.andar(179)
        self.assertFalse(self.relogio.estourou())
        self.tempo.andar(30)
        self.assertTrue(self.relogio.estourou())
        self.assertEqual(self.relogio.restante(), 0)

    def test_maven_usa_o_menor_entre_120_e_o_que_resta(self):
        self.assertEqual(self.relogio.limite_para_teste(120), 120)  # resta 180
        self.tempo.andar(100)
        self.assertEqual(self.relogio.limite_para_teste(120), 80)  # resta 80


if __name__ == "__main__":
    unittest.main()
