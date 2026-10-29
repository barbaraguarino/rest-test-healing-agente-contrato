import re
import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import ResultadoTeste
from agente_contrato.ferramentas import DEFINICOES, montar
from agente_contrato.laco import PedidoFerramenta, executar_pedido
from agente_contrato.relogio import RelogioCaso
from tests.relogio_falso import RelogioFalso

ARQUIVO = "src/test/java/loja/ProdutoTest.java"


class TestDefinicoes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        (self.raiz / ARQUIVO).parent.mkdir(parents=True)
        (self.raiz / ARQUIVO).write_text("class ProdutoTest {\n    void lista() { antigo(); }\n}\n")
        self.maven = []  # (classe, metodo, limite) de cada chamada ao Maven falso

        def rodar(raiz, classe, metodo, limite_s):
            self.maven.append((classe, metodo, limite_s))
            return ResultadoTeste(True, True, 1.0, 0.5)

        self.ferramentas = montar(self.raiz, ARQUIVO, "ProdutoTest", "lista",
                                  RelogioCaso(agora=RelogioFalso()), rodar)

    def pedir(self, nome: str, entrada: dict):
        return executar_pedido(PedidoFerramenta("p1", nome, entrada), self.ferramentas)

    def test_cada_definicao_tem_a_sua_funcao(self):
        self.assertEqual([d["name"] for d in DEFINICOES], list(self.ferramentas))

    def test_definicoes_no_formato_da_api(self):
        for d in DEFINICOES:
            self.assertEqual(set(d), {"name", "description", "input_schema"})
            self.assertRegex(d["name"], r"^[a-zA-Z0-9_-]{1,64}$")
            self.assertEqual(d["input_schema"]["type"], "object")
            self.assertTrue(d["description"].strip())

    def test_descricoes_nao_revelam_o_desenho_do_experimento(self):
        for d in DEFINICOES:
            self.assertIsNone(re.search(r"legítim|problema real|oráculo|categoria|matriz",
                                        d["description"], re.IGNORECASE), d["name"])

    def test_ler_arquivo_recebe_o_caminho_do_modelo(self):
        self.assertIn("antigo()", self.pedir("ler_arquivo", {"caminho": ARQUIVO}).conteudo)

    def test_rodar_teste_usa_o_teste_afetado(self):
        self.assertEqual(self.pedir("rodar_teste", {}).conteudo, "O teste passou.")
        self.assertEqual(self.maven, [("ProdutoTest", "lista", 120)])

    def test_salvar_reparo_grava_no_arquivo_afetado(self):
        self.pedir("salvar_reparo", {"metodo_reparado": "void lista() { novo(); }"})
        self.assertIn("novo()", (self.raiz / ARQUIVO).read_text())

    def test_campo_faltando_volta_ao_modelo_como_erro(self):
        resultado = self.pedir("salvar_reparo", {})
        self.assertTrue(resultado.erro)
        self.assertIn("metodo_reparado", resultado.conteudo)


if __name__ == "__main__":
    unittest.main()
