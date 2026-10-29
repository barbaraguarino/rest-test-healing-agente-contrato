import unittest

from agente_contrato.teste_java import ErroDeAnalise, _depois_do_literal


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


if __name__ == "__main__":
    unittest.main()
