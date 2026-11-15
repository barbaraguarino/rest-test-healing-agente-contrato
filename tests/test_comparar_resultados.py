"""A ferramenta que aplica o comparador a uma rodada gravada (T50): o que ela pode e não pode mudar."""
import tempfile
import unittest
from pathlib import Path

from agente_contrato import comparar_resultados as cr
from tests.test_comparador import java

REG = {"id_caso": "A1-901", "tratamento": "agentes", "repeticao": 1, "rotulo_oraculo": "legitima",
       "compilou": True, "passou": True, "assercoes_enfraquecidas": False,
       "equivalente_oraculo": None, "cenario_alterado": None}


class MesclarTest(unittest.TestCase):
    def test_preenche_os_nulos(self):
        novo = cr._mesclar(REG, {"equivalente_oraculo": True, "cenario_alterado": False}, None)
        self.assertEqual((novo["equivalente_oraculo"], novo["cenario_alterado"]), (True, False))

    def test_nao_sobrescreve_valor_gravado_diferente(self):
        r = {**REG, "cenario_alterado": True}
        with self.assertRaises(ValueError):
            cr._mesclar(r, {"equivalente_oraculo": True, "cenario_alterado": False}, None)

    def test_mantem_o_veredito_da_revisao_manual(self):  # D110: a Barbara gravou false, o comparador dá nulo
        r = {**REG, "equivalente_oraculo": False, "cenario_alterado": False}
        anterior = {"revisao_manual": "D80: ...", "veredito_manual": False}
        novo = cr._mesclar(r, {"equivalente_oraculo": None, "cenario_alterado": False}, anterior)
        self.assertIs(novo["equivalente_oraculo"], False)


class CompararExecucaoTest(unittest.TestCase):
    def _executar(self, antes, depois, esperado):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "antes.java").write_text(antes, encoding="utf-8")
            (Path(d) / "depois.java").write_text(depois, encoding="utf-8")
            caso = cr.DoCaso("teste", esperado, [], {"POST": {"/pedidos"}})
            return cr.comparar_execucao(REG, Path(d), caso)

    def test_equivalente_sem_revisao(self):
        campos, entrada = self._executar(java('{"a": 1}'), java('{"a":1}'), java('{"a": 1}'))
        self.assertEqual(campos, {"equivalente_oraculo": True, "cenario_alterado": False})
        self.assertEqual((entrada["regra"], entrada["revisao_manual"]), (1, None))

    def test_revisao_manual_sai_com_equivalente_nulo(self):  # D110
        campos, entrada = self._executar(java('{"a": 1}'), java('{"a": 1}', asserts=""), java('{"a": 1}'))
        self.assertIsNone(campos["equivalente_oraculo"])
        self.assertFalse(entrada["equivalente_regra"])
        self.assertIn("D80", entrada["revisao_manual"])

    def test_regressao_preenche_so_o_cenario(self):  # D119
        campos, entrada = self._executar(java('{"a": 1}'), java('{"a": 2}'), None)
        self.assertEqual(campos, {"equivalente_oraculo": None, "cenario_alterado": True})
        self.assertIsNone(entrada["revisao_manual"])


if __name__ == "__main__":
    unittest.main()
