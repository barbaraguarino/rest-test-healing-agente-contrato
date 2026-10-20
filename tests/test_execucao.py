import subprocess
import tempfile
import unittest
from pathlib import Path

from agente_contrato import execucao as ex

XML = '<testsuite tests="{t}" failures="{f}" errors="{e}" skipped="{s}" time="{tempo}"/>'


def falso_mvnw(raiz: Path, *, xmls=(), codigo=0, saida="", dorme=0):
    """Cria um mvnw de mentira que escreve relatórios do Surefire e sai com `codigo`."""
    linhas = ["#!/bin/bash", f"sleep {dorme}", "mkdir -p target/surefire-reports"]
    for i, xml in enumerate(xmls):
        linhas.append(f"cat > target/surefire-reports/TEST-x{i}.xml <<'EOF'\n{xml}\nEOF")
    linhas += [f"echo '{saida}'", f"exit {codigo}"]
    caminho = raiz / "mvnw"
    caminho.write_text("\n".join(linhas) + "\n")
    caminho.chmod(0o755)


class RodarTesteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def rodar(self, **kw):
        timeout = kw.pop("timeout_s", 30)
        falso_mvnw(self.raiz, **kw)
        return ex.rodar_teste(self.raiz, "PedidoControllerTest", "teste", timeout)

    def test_teste_que_passa(self):
        r = self.rodar(xmls=[XML.format(t=1, f=0, e=0, s=0, tempo="0.5")])
        self.assertEqual((r.compilou, r.passou, r.duracao_teste_s), (True, True, 0.5))

    def test_teste_que_falha(self):
        r = self.rodar(xmls=[XML.format(t=1, f=1, e=0, s=0, tempo="0.2")], codigo=1)
        self.assertEqual((r.compilou, r.passou), (True, False))

    def test_erro_de_execucao_do_teste_tambem_reprova(self):
        r = self.rodar(xmls=[XML.format(t=1, f=0, e=1, s=0, tempo="0.2")], codigo=1)
        self.assertFalse(r.passou)

    def test_erro_de_compilacao(self):
        r = self.rodar(saida="[ERROR] COMPILATION ERROR :", codigo=1)
        self.assertEqual((r.compilou, r.passou, r.duracao_teste_s), (False, False, 0.0))

    def test_zero_testes_nao_vale_como_passou(self):
        with self.assertRaises(ex.ErroDeExecucao) as e:
            self.rodar(xmls=[XML.format(t=0, f=0, e=0, s=0, tempo="0")])
        self.assertEqual(e.exception.codigo, "erro_execucao")

    def test_mais_de_um_teste_nao_vale(self):
        with self.assertRaises(ex.ErroDeExecucao):
            self.rodar(xmls=[XML.format(t=1, f=0, e=0, s=0, tempo="1"),
                             XML.format(t=1, f=0, e=0, s=0, tempo="1")])

    def test_teste_ignorado_nao_vale_como_passou(self):
        r = self.rodar(xmls=[XML.format(t=1, f=0, e=0, s=1, tempo="0")])
        self.assertFalse(r.passou)

    def test_sem_relatorio_e_erro_de_infraestrutura(self):
        falso_mvnw(self.raiz, codigo=1)
        (self.raiz / "mvnw").write_text("#!/bin/bash\nexit 1\n")
        with self.assertRaises(ex.ErroDeExecucao):
            ex.rodar_teste(self.raiz, "A", "b", 30)

    def test_relatorio_antigo_e_apagado_antes_de_rodar(self):
        pasta = self.raiz / "target" / "surefire-reports"
        pasta.mkdir(parents=True)
        (pasta / "TEST-velho.xml").write_text(XML.format(t=1, f=0, e=0, s=0, tempo="9"))
        (self.raiz / "mvnw").write_text("#!/bin/bash\nexit 0\n")
        (self.raiz / "mvnw").chmod(0o755)
        with self.assertRaises(ex.ErroDeExecucao):  # sem relatório novo: não reaproveita o velho
            ex.rodar_teste(self.raiz, "A", "b", 30)

    def test_timeout_tem_codigo_proprio(self):
        with self.assertRaises(ex.ErroDeExecucao) as e:
            self.rodar(dorme=5, timeout_s=0.5)
        self.assertEqual(e.exception.codigo, "timeout")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


class CopiaEPatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.api = self.base / "api"
        (self.api / "src/test/java/p").mkdir(parents=True)
        (self.api / "a.txt").write_text("um\n")
        (self.api / "src/test/java/p/FooTest.java").write_text("class FooTest {}\n")
        git(self.api, "init", "-q")
        git(self.api, "add", ".")
        git(self.api, "commit", "-q", "-m", "x")
        git(self.api, "tag", "v1")
        (self.api / "a.txt").write_text("dois\n")
        git(self.api, "commit", "-qam", "y")

    def test_copia_fica_na_tag_e_nao_altera_a_origem(self):
        copia = ex.preparar_copia(self.api, "v1", self.base / "copia")
        self.assertEqual((copia / "a.txt").read_text(), "um\n")
        self.assertEqual((self.api / "a.txt").read_text(), "dois\n")

    def test_copia_em_pasta_existente_falha(self):
        (self.base / "copia").mkdir()
        with self.assertRaises(ex.ErroDeExecucao):
            ex.preparar_copia(self.api, "v1", self.base / "copia")

    def test_tag_inexistente_falha(self):
        with self.assertRaises(ex.ErroDeExecucao):
            ex.preparar_copia(self.api, "nao-existe", self.base / "copia")

    def test_aplicar_patch_e_patch_invalido(self):
        copia = ex.preparar_copia(self.api, "v1", self.base / "copia")
        (copia / "a.txt").write_text("tres\n")
        diff = subprocess.run(["git", "diff"], cwd=copia, capture_output=True, text=True, check=True)
        (self.base / "p.patch").write_text(diff.stdout)
        (copia / "a.txt").write_text("um\n")
        ex.aplicar_patch(copia, self.base / "p.patch")
        self.assertEqual((copia / "a.txt").read_text(), "tres\n")
        with self.assertRaises(ex.ErroDeExecucao):  # já aplicado: não aplica de novo
            ex.aplicar_patch(copia, self.base / "p.patch")

    def test_arquivo_de_teste(self):
        self.assertTrue(ex.arquivo_de_teste(self.api, "FooTest").name == "FooTest.java")
        with self.assertRaises(ex.ErroDeExecucao):
            ex.arquivo_de_teste(self.api, "BarTest")


if __name__ == "__main__":
    unittest.main()
