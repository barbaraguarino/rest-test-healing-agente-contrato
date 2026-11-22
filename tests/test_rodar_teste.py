import sys
import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import ErroDeExecucao, rodar_teste

MAVEN_FALSO = Path(__file__).parent / "maven_falso.py"


class TestRodarTeste(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def rodar(self, modo: str, limite_s: float = 10):
        return rodar_teste(self.raiz, "ApiTest", "metodo", limite_s,
                           comando=[sys.executable, str(MAVEN_FALSO), modo])

    def test_teste_que_passa(self):
        r = self.rodar("passa")
        self.assertTrue(r.compilou)
        self.assertTrue(r.passou)
        self.assertEqual(r.duracao_teste_s, 2.5)

    def test_teste_que_falha(self):
        r = self.rodar("falha")
        self.assertTrue(r.compilou)
        self.assertFalse(r.passou)

    def test_codigo_que_nao_compila(self):
        r = self.rodar("nao_compila")
        self.assertFalse(r.compilou)
        self.assertFalse(r.passou)

    def test_zero_testes_e_erro_e_nao_sucesso(self):
        with self.assertRaises(ErroDeExecucao) as ctx:
            self.rodar("zero_testes")
        self.assertEqual(ctx.exception.codigo, "erro_execucao")

    def test_sumula_velha_nao_e_lida(self):
        self.rodar("passa")
        with self.assertRaises(ErroDeExecucao):  # sem a limpeza, leria o "passou" anterior
            self.rodar("nao_gera_nada")

    def test_estouro_do_limite_e_timeout(self):
        with self.assertRaises(ErroDeExecucao) as ctx:
            self.rodar("lento", limite_s=0.5)
        self.assertEqual(ctx.exception.codigo, "timeout")


if __name__ == "__main__":
    unittest.main()
