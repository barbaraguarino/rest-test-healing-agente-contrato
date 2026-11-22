import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import RelatorioSurefire, ler_relatorios


def relatorio_xml(tests: int, failures: int = 0, errors: int = 0, skipped: int = 0,
                  time: float = 1.5) -> str:
    """Só a linha de cima de um TEST-*.xml do Surefire, que é a que o leitor usa."""
    return (f'<testsuite name="ApiTest" tests="{tests}" failures="{failures}" '
            f'errors="{errors}" skipped="{skipped}" time="{time}"></testsuite>')


class TestLerRelatorios(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_um_teste_que_passou(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(1))
        self.assertEqual(ler_relatorios(self.pasta), RelatorioSurefire(1, 0, 0, 0, 1.5))

    def test_um_teste_que_falhou(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(1, failures=1))
        self.assertEqual(ler_relatorios(self.pasta).falhas, 1)

    def test_soma_mais_de_um_arquivo(self):
        (self.pasta / "TEST-A.xml").write_text(relatorio_xml(1, time=1.0))
        (self.pasta / "TEST-B.xml").write_text(relatorio_xml(2, errors=1, time=2.0))
        r = ler_relatorios(self.pasta)
        self.assertEqual((r.executados, r.erros, r.tempo_s), (3, 1, 3.0))

    def test_filtro_que_nao_casou_da_zero_testes(self):
        # o Surefire diz BUILD SUCCESS, mas ninguém entrou em campo
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(0))
        self.assertEqual(ler_relatorios(self.pasta).executados, 0)

    def test_pasta_que_nao_existe_da_zero(self):
        self.assertEqual(ler_relatorios(self.pasta / "nao-existe"), RelatorioSurefire(0, 0, 0, 0, 0.0))


if __name__ == "__main__":
    unittest.main()
