import tempfile
import unittest
from pathlib import Path

from agente_contrato.ferramentas import LIMITE_LEITURA, ler_arquivo
from agente_contrato.laco import ErroDeFerramenta


class TestLerArquivo(unittest.TestCase):
    """D73: o agente só lê `src/` e, em `docs/`, o contrato e as regras de negócio."""

    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self._pasta.cleanup)
        base = Path(self._pasta.name)
        self.raiz = base / "api"
        for caminho, texto in {
            "src/main/java/Produto.java": "class Produto {}",
            "docs/openapi.json": "{}",
            "docs/regras-de-negocio.md": "# Regras",
            "docs/matriz-de-cobertura.md": "desenho do experimento",
            "README.md": "leia-me",
        }.items():
            arquivo = self.raiz / caminho
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(texto, encoding="utf-8")
        (base / "segredo.txt").write_text("fora da cópia", encoding="utf-8")
        (self.raiz / "src" / "atalho.txt").symlink_to(base / "segredo.txt")

    def recusa(self, caminho: str) -> str:
        with self.assertRaises(ErroDeFerramenta) as ctx:
            ler_arquivo(self.raiz, caminho)
        return str(ctx.exception)

    def test_le_src_e_os_dois_arquivos_de_docs(self):
        self.assertEqual(ler_arquivo(self.raiz, "src/main/java/Produto.java"), "class Produto {}")
        self.assertEqual(ler_arquivo(self.raiz, "docs/openapi.json"), "{}")
        self.assertEqual(ler_arquivo(self.raiz, "./docs/regras-de-negocio.md"), "# Regras")

    def test_recusa_o_que_a_d73_deixa_de_fora(self):
        for caminho in ("docs/matriz-de-cobertura.md", "README.md", "pom.xml"):
            self.assertIn("não permitida", self.recusa(caminho))

    def test_recusa_sair_da_copia(self):
        for caminho in ("src/../README.md", "/etc/passwd", "src/atalho.txt"):
            self.assertIn("não permitida", self.recusa(caminho))

    def test_arquivo_que_nao_existe(self):
        self.assertIn("não encontrado", self.recusa("src/main/java/Pedido.java"))

    def test_arquivo_grande_vem_cortado_e_avisado(self):
        (self.raiz / "src" / "Grande.java").write_text("x" * (LIMITE_LEITURA + 10), encoding="utf-8")
        texto = ler_arquivo(self.raiz, "src/Grande.java")
        self.assertTrue(texto.startswith("x" * LIMITE_LEITURA))
        self.assertIn("cortado", texto[LIMITE_LEITURA:])

    def test_pasta_devolve_a_lista_de_arquivos_prontos_para_pedir(self):
        (self.raiz / "src" / "main" / "java" / "dto").mkdir()
        (self.raiz / "src" / "main" / "java" / "dto" / "ProdutoResponse.java").write_text("", encoding="utf-8")
        self.assertEqual(ler_arquivo(self.raiz, "src/main").splitlines(), [
            "Arquivos em src/main:",
            "- src/main/java/Produto.java",
            "- src/main/java/dto/ProdutoResponse.java",
        ])

    def test_lista_de_src_nao_mostra_o_atalho_para_fora(self):
        self.assertNotIn("atalho", ler_arquivo(self.raiz, "src"))

    def test_pasta_fora_da_d73_continua_recusada(self):
        self.assertIn("não permitida", self.recusa("docs"))


if __name__ == "__main__":
    unittest.main()
