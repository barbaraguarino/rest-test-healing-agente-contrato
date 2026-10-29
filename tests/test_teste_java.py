import unittest

from agente_contrato.teste_java import ErroDeAnalise, _depois_do_literal, localizar_metodo

CLASSE = '''class ProdutoTest {
    @Test
    @Sql("/produtos.sql")
    void lista() throws Exception {
        // a resposta tem } no comentário
        mockMvc.perform(post("/produtos").content("""
            { "nome": "x" }
            """))
            .andExpect(jsonPath("$.descricao").value("a { b"));
        if (ok) { contar('}'); }
    }

    @Test
    void outro() {
    }
}
'''


class TestDepoisDoLiteral(unittest.TestCase):
    """Cada caso começa o texto no literal ou comentário e espera o índice logo depois dele."""

    def test_codigo_comum_nao_anda(self):
        self.assertEqual(_depois_do_literal("{ x }", 0), 0)

    def test_texto_entre_aspas(self):
        texto = '"a { b" + x'
        self.assertEqual(texto[_depois_do_literal(texto, 0):], " + x")

    def test_aspas_escapadas_nao_fecham_o_texto(self):
        texto = r'"diz \"oi\" {" ;'
        self.assertEqual(texto[_depois_do_literal(texto, 0):], " ;")

    def test_caractere(self):
        texto = "'{' ;"
        self.assertEqual(texto[_depois_do_literal(texto, 0):], " ;")

    def test_text_block(self):
        texto = '"""\n{ "nome": "x" }\n""" ;'
        self.assertEqual(texto[_depois_do_literal(texto, 0):], " ;")

    def test_comentario_de_linha(self):
        texto = "// fecha } aqui\nx"
        self.assertEqual(texto[_depois_do_literal(texto, 0):], "\nx")

    def test_comentario_de_bloco(self):
        texto = "/* { } */ x"
        self.assertEqual(texto[_depois_do_literal(texto, 0):], " x")

    def test_text_block_sem_fechamento(self):
        with self.assertRaises(ErroDeAnalise):
            _depois_do_literal('"""\n{ aberto', 0)

    def test_comentario_sem_fechamento(self):
        with self.assertRaises(ErroDeAnalise):
            _depois_do_literal("/* aberto", 0)


class TestLocalizarMetodo(unittest.TestCase):
    def test_acha_o_corpo_inteiro_com_chaves_em_textos_e_comentarios(self):
        m = localizar_metodo(CLASSE, "lista")
        corpo = CLASSE[m.inicio:m.fim]
        self.assertTrue(corpo.startswith("{\n        // a resposta"))
        self.assertTrue(corpo.endswith("contar('}'); }\n    }"))

    def test_anotacoes_e_assinatura_ficam_fora_do_corpo(self):
        m = localizar_metodo(CLASSE, "lista")
        self.assertTrue(CLASSE[:m.inicio].endswith('@Sql("/produtos.sql")\n    void lista() throws Exception '))

    def test_nome_que_e_prefixo_de_outro_nao_casa(self):
        with self.assertRaisesRegex(ErroDeAnalise, "0 ocorrências"):
            localizar_metodo(CLASSE, "list")

    def test_metodo_repetido(self):
        with self.assertRaisesRegex(ErroDeAnalise, "2 ocorrências"):
            localizar_metodo(CLASSE + "class B { void lista() {} }", "lista")

    def test_metodo_sem_fechamento(self):
        with self.assertRaisesRegex(ErroDeAnalise, "sem fechamento"):
            localizar_metodo("void lista() { if (x) {", "lista")


if __name__ == "__main__":
    unittest.main()
