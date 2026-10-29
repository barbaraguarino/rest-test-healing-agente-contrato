import tempfile
import unittest
from pathlib import Path

from agente_contrato.ferramentas import salvar_reparo
from agente_contrato.laco import ErroDeFerramenta

ARQUIVO = "src/test/java/loja/ProdutoTest.java"

ORIGINAL = '''class ProdutoTest {
    @Test
    @Sql("/produtos.sql")
    void lista() throws Exception {
        mockMvc.perform(get("/produtos")).andExpect(jsonPath("$.descricao").exists());
    }

    @Test
    void outro() {
        contar();
    }
}
'''


class TestSalvarReparo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.caminho = self.raiz / ARQUIVO
        self.caminho.parent.mkdir(parents=True)
        self.caminho.write_text(ORIGINAL, encoding="utf-8")

    def salvar(self, metodo_reparado: str) -> str:
        return salvar_reparo(self.raiz, ARQUIVO, "lista", metodo_reparado)

    def test_troca_so_o_corpo(self):
        resposta = self.salvar('void lista() {\n        reparado("$.resumo");\n    }')
        self.assertIn("lista", resposta)
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), ORIGINAL.replace(
            '{\n        mockMvc.perform(get("/produtos")).andExpect(jsonPath("$.descricao").exists());\n    }',
            '{\n        reparado("$.resumo");\n    }'))

    def test_anotacoes_e_assinatura_do_modelo_sao_ignoradas(self):
        self.salvar('@Sql("/outro.sql")\npublic void lista() throws Throwable { novo(); }')
        texto = self.caminho.read_text(encoding="utf-8")
        self.assertIn('@Sql("/produtos.sql")\n    void lista() throws Exception { novo(); }', texto)
        self.assertNotIn("/outro.sql", texto)

    def test_metodo_renomeado_volta_ao_modelo_como_erro(self):
        with self.assertRaisesRegex(ErroDeFerramenta, "lista"):
            self.salvar("void listaNova() { novo(); }")
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), ORIGINAL)

    def test_chaves_desequilibradas_voltam_ao_modelo_como_erro(self):
        with self.assertRaises(ErroDeFerramenta):
            self.salvar("void lista() { if (x) { novo(); }")
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), ORIGINAL)

    def test_salvar_de_novo_troca_o_corpo_atual(self):
        self.salvar("void lista() { primeiro(); }")
        self.salvar("void lista() { segundo(); }")
        texto = self.caminho.read_text(encoding="utf-8")
        self.assertIn("void lista() throws Exception { segundo(); }", texto)
        self.assertNotIn("primeiro", texto)


if __name__ == "__main__":
    unittest.main()
