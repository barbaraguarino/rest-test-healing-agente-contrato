import tempfile
import unittest
from pathlib import Path

from agente_contrato import baseline as b
from agente_contrato import resultados
from agente_contrato import rodar_baseline as rb

ORIGINAL = '''class T {
    void teste() throws Exception {
        mockMvc.perform(post("/pedidos")
                        .content("""
                                {"a": 1, "nome": "x"}
                                """))
                .andExpect(status().isCreated());
    }
}
'''
REPARADO = ORIGINAL.replace('"nome"', '"titulo"')
ORACULO = {"id_caso": "A1-999", "categoria": "renomeacao", "rotulo_oraculo": "legitima",
           "correcao_esperada": "casos/esperado.patch"}


def execucao(**kw):
    from agente_contrato import contrato as c
    p = c.Propriedade("string", None, None, False)
    base = dict(id_caso="A1-999", classe="T", metodo="teste", decisao=b.REPARAR, compilou=True,
                passou=True, erro=None, tempo_s=0.0123456, original=ORIGINAL, reparado=REPARADO,
                arquivo_relativo="src/test/java/T.java",
                mudancas=[c.Mudanca(c.RENOMEACAO, "POST", "/pedidos", c.REQUISICAO, "nome", "titulo", p, p)],
                rotas={"POST": {"/pedidos"}})
    base.update(kw)
    return rb.Execucao(**base)


class RegistrarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        (self.raiz / "casos").mkdir()
        alvo = self.raiz / "src/test/java/T.java"
        alvo.parent.mkdir(parents=True)
        alvo.write_text(ORIGINAL)
        patch = ("--- a/src/test/java/T.java\n+++ b/src/test/java/T.java\n@@ -3,5 +3,5 @@\n"
                 '         mockMvc.perform(post("/pedidos")\n'
                 '                         .content("""\n'
                 '-                                {"a": 1, "nome": "x"}\n'
                 '+                                {"a": 1, "titulo": "x"}\n'
                 '                                 """))\n'
                 '                 .andExpect(status().isCreated());\n')
        (self.raiz / "casos/esperado.patch").write_text(patch)

    def test_equivalente_com_troca_de_cenario_vai_para_revisao_manual(self):
        from unittest import mock
        from agente_contrato import comparador
        contraditorio = comparador.Comparacao(True, True, ())
        with mock.patch.object(rb.comparador, "comparar", return_value=contraditorio):
            _, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertTrue(extras["revisao_manual"])
        self.assertIn("inconsistência", " ".join(extras["motivos"]))

    def test_reparo_coerente_nao_vai_para_revisao_manual(self):
        _, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertFalse(extras["revisao_manual"])

    def test_registro_de_reparo_equivalente_e_valido_na_d74(self):
        registro, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertEqual((registro["decisao"], registro["equivalente_oraculo"],
                          registro["cenario_alterado"], registro["assercoes_enfraquecidas"]),
                         ("reparar", True, False, False))
        self.assertEqual(registro["tempo_s"], 0.0123)
        self.assertFalse(extras["revisao_manual"])

    def test_oraculo_so_entra_no_registro(self):
        registro, _ = rb.registrar(execucao(), ORACULO, 2, self.raiz)
        self.assertEqual((registro["categoria"], registro["rotulo_oraculo"], registro["repeticao"]),
                         ("renomeacao", "legitima", 2))

    def test_nao_reparar_deixa_os_campos_de_reparo_nulos(self):
        e = execucao(decisao=b.NAO_REPARAR, compilou=None, passou=False, reparado=None)
        registro, extras = rb.registrar(e, ORACULO, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertEqual([registro[c] for c in ("compilou", "equivalente_oraculo",
                                                "assercoes_enfraquecidas", "cenario_alterado")], [None] * 4)
        self.assertFalse(extras["revisao_manual"])

    def test_regressao_reparada_tem_equivalente_nulo_e_sem_revisao_manual(self):
        oraculo = {**ORACULO, "rotulo_oraculo": "problema_real", "correcao_esperada": None}
        registro, extras = rb.registrar(execucao(passou=False), oraculo, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertIsNone(registro["equivalente_oraculo"])
        self.assertFalse(extras["revisao_manual"])

    def test_reparo_que_passa_mas_a_regra_reprova_vai_para_revisao_manual(self):
        outro = REPARADO.replace('"a": 1', '"a": 2')  # valor diferente da correção esperada
        _, extras = rb.registrar(execucao(reparado=outro), ORACULO, 1, self.raiz)
        self.assertTrue(extras["revisao_manual"])

    def test_erro_de_guarda_fica_registrado(self):
        e = execucao(decisao=b.NAO_REPARAR, compilou=None, passou=False, reparado=None, erro="guarda")
        registro, _ = rb.registrar(e, ORACULO, 1, self.raiz)
        self.assertEqual((registro["decisao"], registro["erro"]), ("nao_reparar", "guarda"))
        self.assertEqual(resultados.problemas(registro), [])

    def test_assinatura_ignora_tempo_e_repeticao_mas_nao_o_conteudo(self):
        r1, _ = rb.registrar(execucao(tempo_s=1.0), ORACULO, 1, self.raiz)
        r2, _ = rb.registrar(execucao(tempo_s=9.0), ORACULO, 2, self.raiz)
        self.assertEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r2, REPARADO))
        self.assertNotEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r1, REPARADO + " "))
        r3, _ = rb.registrar(execucao(passou=False), ORACULO, 3, self.raiz)
        self.assertNotEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r3, REPARADO))


if __name__ == "__main__":
    unittest.main()
