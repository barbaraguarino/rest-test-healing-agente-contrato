"""O que a T50 acrescentou ao comparador da v1: a regra da D95 que decidiu e a revisão manual (D80, D109)."""
import unittest

from agente_contrato import comparador as cp
from agente_contrato import contrato as c
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


def muda_tipo(caminho, antes, depois):
    return c.Mudanca(c.ALTERACAO_TIPO, "POST", "/pedidos", c.REQUISICAO, caminho,
                     antes=c.Propriedade(antes, None, None, False), depois=c.Propriedade(depois, None, None, False))


class AlteracaoDeTipoTest(unittest.TestCase):
    """O campo que vira array é atingido pela diferença, inclusive o que fica dentro dele (A1-027 da T25)."""
    ORIG = java('{"a": 1, "d": "x y"}')
    MUDA = muda_tipo("d", "string", "array")

    def test_campo_que_vira_array_nao_troca_cenario(self):
        r = comparar(self.ORIG, java('{"a": 1, "d": ["x y"]}'), java('{"a": 1, "d": ["x y"]}'), self.MUDA)
        self.assertEqual((r.equivalente, r.cenario_alterado, r.regra), (True, False, 1))

    def test_valor_diferente_do_esperado_no_campo_que_mudou_de_tipo_nao_e_equivalente(self):
        r = comparar(self.ORIG, java('{"a": 1, "d": ["x", "y"]}'), java('{"a": 1, "d": ["x y"]}'), self.MUDA)
        self.assertEqual((r.equivalente, r.cenario_alterado), (False, False))

    def test_outro_campo_mudado_continua_trocando_cenario(self):
        r = comparar(self.ORIG, java('{"a": 2, "d": ["x y"]}'), None, self.MUDA)
        self.assertTrue(r.cenario_alterado)


if __name__ == "__main__":
    unittest.main()
