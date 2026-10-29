import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import LIMITE_MENSAGEM, Falha, ler_falha


def relatorio_xml(*testcases: str) -> str:
    """Um TEST-*.xml do Surefire com os <testcase> dados; o leitor de falha só olha o que há dentro deles."""
    return '<testsuite name="ApiTest" tests="1">' + "".join(testcases) + "</testsuite>"


class TestLerFalha(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_failure_com_message(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(
            '<testcase name="lista"><failure message="No value at JSON path &quot;$.descricao&quot;" '
            'type="java.lang.AssertionError">java.lang.AssertionError: No value\n\tat Foo.bar(Foo.java:1)'
            '</failure></testcase>'))
        self.assertEqual(ler_falha(self.pasta), Falha("failure", "java.lang.AssertionError",
                                                      'No value at JSON path "$.descricao"'))

    def test_error_sem_message_usa_a_primeira_linha_sem_stack_trace(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(
            '<testcase name="lista"><error type="java.lang.NullPointerException">'
            'java.lang.NullPointerException\n\tat Foo.bar(Foo.java:1)\n\tat Foo.baz(Foo.java:2)'
            '</error></testcase>'))
        self.assertEqual(ler_falha(self.pasta), Falha("error", "java.lang.NullPointerException",
                                                      "java.lang.NullPointerException"))

    def test_mensagem_longa_e_cortada(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml(
            f'<testcase name="lista"><failure message="{"x" * 5000}" type="E"/></testcase>'))
        mensagem = ler_falha(self.pasta).mensagem
        self.assertEqual(len(mensagem), LIMITE_MENSAGEM)
        self.assertTrue(mensagem.endswith(" [...]"))

    def test_teste_que_passou_da_none(self):
        (self.pasta / "TEST-ApiTest.xml").write_text(relatorio_xml('<testcase name="lista"/>'))
        self.assertIsNone(ler_falha(self.pasta))

    def test_pasta_que_nao_existe_da_none(self):
        # o teste não compilou, então o Surefire não escreveu relatório
        self.assertIsNone(ler_falha(self.pasta / "nao-existe"))


if __name__ == "__main__":
    unittest.main()
