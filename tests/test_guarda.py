"""Os testes de GuardaTest são os da tag rodada-2, sem mudança (gabarito da T23g)."""
import unittest

from agente_contrato import contrato as c
from agente_contrato import guarda as g

ROTAS = {"GET": {"/produtos/{id}"}}
ORIGINAL = '''class T {
    @Test
    @Sql("/a.sql")
    void teste() throws Exception {
        mockMvc.perform(get("/produtos/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.nome").value("x"))
                .andExpect(jsonPath("$.estoque").value(is(3)));
    }

    @Test
    void outro() throws Exception {
    }
}
'''
REMOCAO_ESTOQUE = c.Mudanca(c.REMOCAO, "GET", "/produtos/{id}", c.RESPOSTA, "estoque",
                            antes=c.Propriedade("integer", None, None, False))


def avaliar(depois, mudancas=()):
    return g.avaliar(ORIGINAL, depois, "teste", list(mudancas), ROTAS)


class GuardaTest(unittest.TestCase):
    def test_reparo_que_so_renomeia_e_aceito(self):
        self.assertTrue(avaliar(ORIGINAL.replace("$.nome", "$.titulo")).aceito)

    def test_menos_asserções_e_recusado(self):
        v = avaliar(ORIGINAL.replace('                .andExpect(jsonPath("$.nome").value("x"))\n', ""))
        self.assertFalse(v.aceito)
        self.assertIn("menos asserções", v.motivos[0])

    def test_remover_asserção_de_campo_removido_pelo_contrato_e_aceito(self):
        depois = ORIGINAL.replace('\n                .andExpect(jsonPath("$.estoque").value(is(3)));', ";")
        self.assertFalse(avaliar(depois).aceito)                       # sem a exceção da D77
        self.assertTrue(avaliar(depois, [REMOCAO_ESTOQUE]).aceito)     # com ela

    def test_a_excecao_nao_cobre_remover_outra_asserção(self):
        depois = ORIGINAL.replace('                .andExpect(jsonPath("$.nome").value("x"))\n', "")
        self.assertFalse(avaliar(depois, [REMOCAO_ESTOQUE]).aceito)

    def test_limite_trocar_uma_asserção_por_outra_nao_e_pego_pelo_guarda(self):
        depois = ORIGINAL.replace('.andExpect(jsonPath("$.nome").value("x"))',
                                  '.andExpect(jsonPath("$.novo").value("y"))').replace(
            '\n                .andExpect(jsonPath("$.estoque").value(is(3)));', ";")
        # O guarda conta asserções; trocar uma por outra é assunto do comparador (troca de cenário).
        self.assertTrue(avaliar(depois, [REMOCAO_ESTOQUE]).aceito)

    def test_teste_removido(self):
        depois = ORIGINAL.replace("    @Test\n    void outro() throws Exception {\n    }\n", "")
        self.assertFalse(avaliar(depois).aceito)

    def test_metodo_afetado_removido(self):
        v = g.avaliar(ORIGINAL, ORIGINAL.replace("void teste()", "void renomeado()"), "teste", [], ROTAS)
        self.assertFalse(v.aceito)
        self.assertIn("não encontrado", v.motivos[-1])

    def test_disabled(self):
        v = avaliar(ORIGINAL.replace("    @Sql", "    @Disabled\n    @Sql"))
        self.assertIn("@Disabled acrescentado", v.motivos)

    def test_matcher_afrouxado(self):
        for fraco in ("anything()", "notNullValue()"):
            v = avaliar(ORIGINAL.replace("value(is(3))", f"value({fraco})"))
            self.assertIn("matcher afrouxado", v.motivos, fraco)
        v = avaliar(ORIGINAL.replace("status().isOk()", "status().is2xxSuccessful()"))
        self.assertIn("matcher afrouxado", v.motivos)


class ForaDoMetodoTest(unittest.TestCase):  # D116
    MOTIVO = "alteração fora do corpo do método afetado"

    def test_sql_trocado_e_recusado(self):
        v = avaliar(ORIGINAL.replace('@Sql("/a.sql")', '@Sql("/b.sql")'))
        self.assertFalse(v.aceito)
        self.assertEqual(v.motivos, (self.MOTIVO,))

    def test_sql_acrescentado_e_recusado(self):
        v = avaliar(ORIGINAL.replace("    @Test\n    void outro()", '    @Test\n    @Sql("/b.sql")\n    void outro()'))
        self.assertIn(self.MOTIVO, v.motivos)

    def test_assinatura_trocada_e_recusada(self):
        v = avaliar(ORIGINAL.replace("void teste() throws Exception", "void teste() throws Throwable"))
        self.assertIn(self.MOTIVO, v.motivos)

    def test_outro_metodo_alterado_e_recusado(self):
        v = avaliar(ORIGINAL.replace("void outro() throws Exception {\n", "void outro() throws Exception {\n        x();\n"))
        self.assertIn(self.MOTIVO, v.motivos)

    def test_import_acrescentado_e_recusado(self):
        v = avaliar("import static x.Y.*;\n" + ORIGINAL)
        self.assertIn(self.MOTIVO, v.motivos)

    def test_mudanca_so_no_corpo_e_aceita(self):
        self.assertTrue(avaliar(ORIGINAL.replace("/produtos/1", "/produtos/2")).aceito)


if __name__ == "__main__":
    unittest.main()
