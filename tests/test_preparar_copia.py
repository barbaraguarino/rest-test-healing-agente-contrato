import subprocess
import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import ErroDeExecucao, aplicar_patch, preparar_copia


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "user.name=teste", "-c", "user.email=teste@exemplo",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def repositorio_com_tag(raiz: Path) -> Path:
    """Repositório pequeno: a tag `base` marca o primeiro commit, e há um segundo depois dela."""
    origem = raiz / "origem"
    origem.mkdir()
    git("init", "-q", cwd=origem)
    (origem / "Api.java").write_text("versao 1\n")
    git("add", ".", cwd=origem)
    git("commit", "-q", "-m", "primeiro", cwd=origem)
    git("tag", "base", cwd=origem)
    (origem / "Api.java").write_text("versao 2\n")
    git("commit", "-q", "-am", "segundo", cwd=origem)
    return origem


class TestPrepararCopia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.origem = repositorio_com_tag(self.raiz)

    def tearDown(self):
        self._tmp.cleanup()

    def test_copia_fica_na_tag_e_nao_no_ultimo_commit(self):
        copia = preparar_copia(self.origem, "base", self.raiz / "copia")
        self.assertEqual((copia / "Api.java").read_text(), "versao 1\n")

    def test_destino_que_ja_existe_e_recusado(self):
        (self.raiz / "copia").mkdir()
        with self.assertRaises(ErroDeExecucao):
            preparar_copia(self.origem, "base", self.raiz / "copia")

    def test_tag_que_nao_existe_e_erro_de_execucao(self):
        with self.assertRaises(ErroDeExecucao) as ctx:
            preparar_copia(self.origem, "nao-existe", self.raiz / "copia")
        self.assertEqual(ctx.exception.codigo, "erro_execucao")


PATCH_QUE_ENCAIXA = """\
--- a/Api.java
+++ b/Api.java
@@ -1 +1 @@
-versao 1
+versao 1 com patch
"""

PATCH_QUE_NAO_ENCAIXA = PATCH_QUE_ENCAIXA.replace("-versao 1", "-versao 9")


class TestAplicarPatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.copia = preparar_copia(repositorio_com_tag(self.raiz), "base", self.raiz / "copia")

    def tearDown(self):
        self._tmp.cleanup()

    def escrever_patch(self, texto: str) -> Path:
        patch = self.raiz / "caso.patch"
        patch.write_text(texto)
        return patch

    def test_patch_que_encaixa_muda_o_arquivo(self):
        aplicar_patch(self.copia, self.escrever_patch(PATCH_QUE_ENCAIXA))
        self.assertEqual((self.copia / "Api.java").read_text(), "versao 1 com patch\n")

    def test_patch_que_nao_encaixa_e_erro_e_nao_muda_nada(self):
        with self.assertRaises(ErroDeExecucao):
            aplicar_patch(self.copia, self.escrever_patch(PATCH_QUE_NAO_ENCAIXA))
        self.assertEqual((self.copia / "Api.java").read_text(), "versao 1\n")


if __name__ == "__main__":
    unittest.main()
