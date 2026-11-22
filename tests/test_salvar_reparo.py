import tempfile
import unittest
from pathlib import Path

from agente_contrato.ferramentas import guarda_do_caso, salvar_reparo
from agente_contrato.guarda import Veredito
from agente_contrato.laco import ErroDeFerramenta
from tests.test_preparar_copia import git

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
        # Estes testes tratam da troca do corpo; o guarda aceita tudo e só anota o que recebeu.
        self.conferidos = []

        def aceita(reparado):
            self.conferidos.append(reparado)
            return Veredito(True, ())
        return salvar_reparo(self.raiz, ARQUIVO, "lista", metodo_reparado, aceita)

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


    def test_o_guarda_recebe_o_arquivo_inteiro_ja_reparado(self):
        self.salvar("void lista() { novo(); }")
        self.assertEqual(self.conferidos, [self.caminho.read_text(encoding="utf-8")])

    def test_reparo_recusado_pelo_guarda_nao_e_gravado_e_volta_com_os_motivos(self):  # D129
        def recusa(reparado):
            return Veredito(False, ("menos asserções (0) que o permitido (1)", "matcher afrouxado"))
        with self.assertRaisesRegex(ErroDeFerramenta, r"menos asserções \(0\) .*; matcher afrouxado"):
            salvar_reparo(self.raiz, ARQUIVO, "lista", "void lista() { }", recusa)
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), ORIGINAL)


class TestGuardaDoCaso(unittest.TestCase):
    """O guarda de verdade, numa cópia com git: o contrato da tag é o do HEAD (D129)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.caminho = self.raiz / ARQUIVO
        self.caminho.parent.mkdir(parents=True)
        self.caminho.write_text(ORIGINAL, encoding="utf-8")
        (self.raiz / "docs").mkdir()
        (self.raiz / "docs" / "openapi.json").write_text('{"paths": {}}', encoding="utf-8")
        git("init", "-q", cwd=self.raiz)
        git("add", ".", cwd=self.raiz)
        git("commit", "-q", "-m", "tag", cwd=self.raiz)
        self.conferir = guarda_do_caso(self.raiz, ARQUIVO, "lista")

    def salvar(self, metodo_reparado: str) -> str:
        return salvar_reparo(self.raiz, ARQUIVO, "lista", metodo_reparado, self.conferir)

    def test_reparo_que_mantem_a_assercao_e_gravado(self):
        self.salvar('void lista() { mockMvc.perform(get("/produtos")).andExpect(jsonPath("$.resumo").exists()); }')
        self.assertIn("$.resumo", self.caminho.read_text(encoding="utf-8"))

    def test_reparo_sem_a_assercao_e_recusado(self):
        with self.assertRaisesRegex(ErroDeFerramenta, "menos asserções"):
            self.salvar("void lista() { novo(); }")
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), ORIGINAL)

    def test_cada_reparo_e_comparado_com_o_original_e_nao_com_o_anterior(self):
        self.salvar('void lista() { mockMvc.perform(get("/produtos")).andExpect(jsonPath("$.a").value(is(1)))'
                    '.andExpect(jsonPath("$.b").value(is(2))); }')
        # O primeiro reparo tem duas asserções; voltar a uma é o mesmo número do original e é aceito.
        self.salvar('void lista() { mockMvc.perform(get("/produtos")).andExpect(jsonPath("$.a").value(is(1))); }')
        with self.assertRaisesRegex(ErroDeFerramenta, "menos asserções"):
            self.salvar("void lista() { novo(); }")
        self.assertIn('"$.a"', self.caminho.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
