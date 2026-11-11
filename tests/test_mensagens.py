import unittest

from agente_contrato.agentes import mensagem_classifier, mensagem_repair
from agente_contrato.execucao import Falha

ARQUIVO = "src/test/java/loja/ProdutoTest.java"
METODO = "    @Test\n    void lista() {\n        antigo();\n    }"
FALHA = Falha("failure", "java.lang.AssertionError", "No value at JSON path \"$.nome\"")
DIFERENCA = "- GET /produtos, resposta 200: o campo nome foi renomeado para titulo"


class TestMensagemClassifier(unittest.TestCase):
    def test_leva_o_teste_a_falha_e_o_metodo(self):
        texto = mensagem_classifier(ARQUIVO, "ProdutoTest", "lista", FALHA, METODO)
        self.assertIn("ProdutoTest.lista, no arquivo `src/test/java/loja/ProdutoTest.java`", texto)
        self.assertIn("Tipo: failure (java.lang.AssertionError)", texto)
        self.assertIn("```java\n" + METODO + "\n```", texto)

    def test_nao_leva_a_diferenca(self):  # D125: o Classifier busca a diferença com ver_diferenca
        texto = mensagem_classifier(ARQUIVO, "ProdutoTest", "lista", FALHA, METODO)
        self.assertNotIn("Diferenças", texto)

    def test_teste_que_nao_compilou(self):
        texto = mensagem_classifier(ARQUIVO, "ProdutoTest", "lista", None, METODO)
        self.assertIn("O teste não compilou", texto)


class TestMensagemRepair(unittest.TestCase):
    def test_leva_o_diagnostico_a_diferenca_e_o_teste(self):
        texto = mensagem_repair(ARQUIVO, "ProdutoTest", "lista", FALHA, METODO, DIFERENCA,
                                "legitima", "O campo nome virou titulo no contrato.")
        self.assertIn("Rótulo: legitima\nJustificativa: O campo nome virou titulo no contrato.", texto)
        self.assertIn("## Diferenças entre o contrato OpenAPI antigo e o novo\n" + DIFERENCA, texto)  # D125
        self.assertIn("```java\n" + METODO + "\n```", texto)


if __name__ == "__main__":
    unittest.main()
