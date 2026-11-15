"""O que a T50 acrescentou ao comparador da v1: a regra da D95 que decidiu e a revisão manual (D80, D109)."""
import unittest

from agente_contrato import comparador as cp
from tests.test_comparador import comparar, java, nova


class RegraTest(unittest.TestCase):
    ORIG = java('{"a": 1}')

    def test_identico_e_regra_1(self):
        self.assertEqual(comparar(self.ORIG, java('{"a":1}'), java('{"a": 1}')).regra, 1)

    def test_json_em_outra_ordem_e_regra_2(self):
        self.assertEqual(comparar(self.ORIG, java('{"b": 2, "a": 1}'), java('{"a": 1, "b": 2}')).regra, 2)

    def test_so_o_valor_do_campo_novo_e_regra_3(self):
        r = comparar(self.ORIG, java('{"a": 1, "cpf": "x"}'), java('{"a": 1, "cpf": "1"}'), nova("cpf"))
        self.assertEqual(r.regra, 3)

    def test_nao_equivalente_fica_sem_regra(self):
        self.assertIsNone(comparar(self.ORIG, java('{"a": 2}'), java('{"a": 1}')).regra)


def _cmp(equivalente, cenario):
    return cp.Comparacao(equivalente, cenario, ())


class RevisaoManualTest(unittest.TestCase):
    def test_equivalente_sem_troca_decide_sozinha(self):
        self.assertIsNone(cp.revisao_manual(_cmp(True, False), True, True, True, False))

    def test_cenario_que_a_regra_nao_decide_vai_para_revisao(self):
        self.assertIn("D80", cp.revisao_manual(_cmp(True, None), True, True, True, False))

    def test_equivalencia_que_a_regra_nao_decide_vai_para_revisao(self):
        self.assertIn("D80", cp.revisao_manual(_cmp(None, False), True, True, True, False))

    def test_equivalente_e_com_troca_de_cenario_vai_para_revisao(self):
        self.assertIn("D109", cp.revisao_manual(_cmp(True, True), True, True, True, False))

    def test_nao_equivalente_que_compila_passa_e_nao_enfraquece_vai_para_revisao(self):
        self.assertIn("D80", cp.revisao_manual(_cmp(False, False), True, True, True, False))

    def test_nao_equivalente_que_falha_decide_sozinha(self):
        self.assertIsNone(cp.revisao_manual(_cmp(False, False), True, True, False, False))

    def test_nao_equivalente_que_enfraquece_decide_sozinha(self):
        self.assertIsNone(cp.revisao_manual(_cmp(False, False), True, True, True, True))

    def test_regressao_sem_correcao_esperada_decide_sozinha(self):  # D119
        self.assertIsNone(cp.revisao_manual(_cmp(None, True), False, True, True, False))


if __name__ == "__main__":
    unittest.main()
