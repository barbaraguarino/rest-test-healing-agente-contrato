import tempfile
import unittest
from pathlib import Path

from agente_contrato import leitura_falha as lf

# Formato real do Surefire (relatório da A1-001 em 22/10/2026), reduzido ao essencial.
XML_FALHA = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="ProdutoControllerTest" tests="1" failures="1" errors="0" skipped="0">
  <testcase name="shouldReturn200" classname="ProdutoControllerTest" time="0.4">
    <failure message="No value at JSON path &quot;$.descricao&quot;" type="java.lang.AssertionError">java.lang.AssertionError: No value at JSON path "$.descricao"
\tat org.springframework.test.util.JsonPathExpectationsHelper.evaluateJsonPath(JsonPathExpectationsHelper.java:350)
</failure>
    <system-out>log que não interessa</system-out>
  </testcase>
</testsuite>
"""

XML_ERRO_SEM_MENSAGEM = """<testsuite tests="1" failures="0" errors="1">
  <testcase name="t"><error type="java.lang.NullPointerException">java.lang.NullPointerException
\tat Foo.bar(Foo.java:10)
</error></testcase>
</testsuite>
"""

XML_PASSOU = '<testsuite tests="1" failures="0" errors="0"><testcase name="t"/></testsuite>'


class LerFalhaTest(unittest.TestCase):
    def _raiz_com(self, xml: str | None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pasta = Path(tmp.name, "target", "surefire-reports")
        pasta.mkdir(parents=True)
        if xml is not None:
            (pasta / "TEST-x.xml").write_text(xml, encoding="utf-8")
        return Path(tmp.name)

    def test_le_mensagem_sem_stack_trace(self):
        f = lf.ler_falha(self._raiz_com(XML_FALHA))
        self.assertEqual(f.tipo, "failure")
        self.assertEqual(f.excecao, "java.lang.AssertionError")
        self.assertEqual(f.mensagem, 'No value at JSON path "$.descricao"')
        self.assertNotIn("springframework", f.mensagem)

    def test_sem_atributo_message_usa_primeira_linha_do_corpo(self):
        f = lf.ler_falha(self._raiz_com(XML_ERRO_SEM_MENSAGEM))
        self.assertEqual(f.tipo, "error")
        self.assertEqual(f.mensagem, "java.lang.NullPointerException")

    def test_trunca_mensagem_longa_marcando_o_corte(self):
        xml = f'<testsuite><testcase name="t"><failure message="{"x" * 200}" type="E"/></testcase></testsuite>'
        f = lf.ler_falha(self._raiz_com(xml), limite=50)
        self.assertEqual(len(f.mensagem), 50)
        self.assertTrue(f.mensagem.endswith("[...]"))

    def test_sem_falha_ou_sem_relatorio_devolve_none(self):
        self.assertIsNone(lf.ler_falha(self._raiz_com(XML_PASSOU)))
        self.assertIsNone(lf.ler_falha(self._raiz_com(None)))
        self.assertIsNone(lf.ler_falha(Path(tempfile.gettempdir(), "nao-existe-xyz")))


if __name__ == "__main__":
    unittest.main()
