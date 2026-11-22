"""O relatório visual (T52): só lê, escapa o Java e marca o que falta."""
import tempfile
import unittest
from pathlib import Path

from agente_contrato import relatorio_visual as rv


class EquivalenciaTest(unittest.TestCase):
    def test_nulo_em_legitimo_reparado_e_pendente(self):
        r = {"decisao": "reparar", "rotulo_oraculo": "legitima", "equivalente_oraculo": None}
        self.assertEqual(rv.equivalencia(r, None, False)[0], rv.PENDENTE)

    def test_nulo_em_regressao_nao_e_pendente(self):
        r = {"decisao": "reparar", "rotulo_oraculo": "problema_real", "equivalente_oraculo": None}
        self.assertNotEqual(rv.equivalencia(r, None, False)[0], rv.PENDENTE)

    def test_nao_reparou(self):
        r = {"decisao": "nao_reparar", "rotulo_oraculo": "legitima", "equivalente_oraculo": None}
        self.assertIn("não reparou", rv.equivalencia(r, None, False)[0])

    def test_veredito_gravado_aparece(self):
        r = {"decisao": "reparar", "rotulo_oraculo": "legitima", "equivalente_oraculo": True}
        self.assertEqual(rv.equivalencia(r, None, False)[0], "sim")


class PedacosTest(unittest.TestCase):
    def test_java_e_escapado(self):
        self.assertNotIn("<script>", rv.codigo_html("a<script>alert(1)</script>", "x"))
        self.assertIn("&lt;script&gt;", rv.diff_html("+<script>", "x"))

    def test_diff_destaca_linhas(self):
        h = rv.diff_html("@@ -1 +1 @@\n-a\n+b\n c", "x")
        self.assertIn('class="menos"', h)
        self.assertIn('class="mais"', h)

    def test_nome_da_pasta(self):
        self.assertEqual(rv.nome_da_pasta("A1-013", "agentes", 2), "A1-013-r2")
        self.assertEqual(rv.nome_da_pasta("A1-013", "baseline", 1), "A1-013-baseline-r1")
        self.assertEqual(rv.nome_da_pasta("A1-015", "agente_unico", 3), "A1-015-agente_unico-r3")


class SaidaTest(unittest.TestCase):
    def test_recusa_saida_dentro_de_resultados(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "resultados" / "r").mkdir(parents=True)
            antigo = Path.cwd()
            import os
            os.chdir(raiz)
            try:
                rc = rv.main(["--pasta", "resultados/r", "--saida", "resultados/r/x.html"])
            finally:
                os.chdir(antigo)
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
