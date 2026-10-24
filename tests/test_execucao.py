import inspect
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from agente_contrato import execucao as ex

from .fakes import RelogioFalso

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

    @unittest.skipUnless(hasattr(os, "killpg"), "grupo de processos só no POSIX")
    def test_estouro_encerra_o_mvnw_e_os_filhos(self):
        """O mvnw de mentira abre um filho (no papel do java) que segura o pipe por 60 s."""
        (self.raiz / "mvnw").write_text("#!/bin/bash\nsleep 60 &\necho $! > filho.pid\nsleep 60\n")
        (self.raiz / "mvnw").chmod(0o755)
        inicio = time.monotonic()
        with self.assertRaises(ex.ErroDeExecucao) as e:
            ex.rodar_teste(self.raiz, "A", "b", 0.5)
        self.assertEqual(e.exception.codigo, "timeout")
        self.assertLess(time.monotonic() - inicio, ex.ESPERA_DO_SIGTERM_S + 5)  # não esperou o filho
        pid = int((self.raiz / "filho.pid").read_text())
        self.assertFalse(vivo(pid), f"processo {pid} ficou órfão")


def vivo(pid: int) -> bool:
    """Vivo e não zumbi; espera até 2 s o sistema recolher o processo."""
    fim = time.monotonic() + 2
    while time.monotonic() < fim:
        try:
            estado = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return False
        if estado == "Z":
            return False
        time.sleep(0.05)
    return True


class RodarFalsoComRelogio:
    """Durações simuladas para o Maven: sem processo e sem esperar de verdade."""

    def __init__(self, relogio, duracoes):
        self.relogio, self.duracoes, self.timeouts = relogio, list(duracoes), []

    def __call__(self, raiz, classe, metodo, timeout_s):
        self.timeouts.append(timeout_s)
        d = self.duracoes.pop(0)
        self.relogio.avancar(min(d, timeout_s))
        if d > timeout_s:
            raise ex.ErroDeExecucao("estourou", "timeout", "estouro")
        return ex.ResultadoTeste(True, False, d, 0.1)


class LimitesTest(unittest.TestCase):
    def setUp(self):
        self.relogio = RelogioFalso()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)

    def test_valores_padrao_da_d111(self):
        self.assertEqual((ex.LIMITE_TESTE_S, ex.LIMITE_CASO_S), (120, 180))
        self.assertEqual(inspect.signature(ex.rodar_teste).parameters["timeout_s"].default, 120)
        self.assertEqual((ex.Limites().teste_s, ex.Limites().caso_s), (120, 180))

    def test_a_espera_do_llm_nao_conta_no_caso(self):
        limite = ex.LimiteDoCaso(180, self.relogio)
        self.relogio.avancar(10)
        with limite.fora_da_conta():
            self.relogio.avancar(500)
        self.assertEqual((limite.decorrido(), limite.espera_llm_s, limite.restante()), (10, 500, 170))
        limite.verificar()

    def test_caso_estourado_e_timeout(self):
        limite = ex.LimiteDoCaso(180, self.relogio)
        self.relogio.avancar(180)
        with self.assertRaises(ex.ErroDeExecucao) as e:
            limite.verificar()
        self.assertEqual((e.exception.codigo, e.exception.causa), ("timeout", "caso"))

    def test_maven_inicial_estourado_roda_mais_uma_vez_sem_o_target(self):
        (self.raiz / "target").mkdir()
        rodar = RodarFalsoComRelogio(self.relogio, [200, 10])
        r, tentativas = ex.rodar_teste_inicial(rodar, self.raiz, "A", "b")
        self.assertEqual((tentativas, r.duracao_maven_s, rodar.timeouts), (2, 10, [120, 120]))
        self.assertFalse((self.raiz / "target").exists())

    def test_dois_estouros_do_maven_inicial_sao_erro_execucao(self):
        rodar = RodarFalsoComRelogio(self.relogio, [200, 200])
        with self.assertRaises(ex.ErroDeExecucao) as e:
            ex.rodar_teste_inicial(rodar, self.raiz, "A", "b")
        self.assertEqual((e.exception.codigo, e.exception.causa), ("erro_execucao", "estouro_maven_inicial"))

    def test_outro_erro_do_maven_inicial_nao_se_repete(self):
        chamadas = []

        def rodar(*a, **kw):
            chamadas.append(1)
            raise ex.ErroDeExecucao("0 testes executados")
        with self.assertRaises(ex.ErroDeExecucao):
            ex.rodar_teste_inicial(rodar, self.raiz, "A", "b")
        self.assertEqual(len(chamadas), 1)

    def test_teste_final_usa_o_menor_limite_e_diz_qual_estourou(self):
        limite = ex.LimiteDoCaso(180, self.relogio)
        rodar = RodarFalsoComRelogio(self.relogio, [130])
        with self.assertRaises(ex.ErroDeExecucao) as e:
            ex.rodar_teste_final(rodar, self.raiz, "A", "b", limite)
        self.assertEqual((e.exception.codigo, e.exception.causa, rodar.timeouts), ("timeout", "teste_final", [120]))

        limite = ex.LimiteDoCaso(180, self.relogio)
        self.relogio.avancar(100)  # sobram 80 s do caso
        rodar = RodarFalsoComRelogio(self.relogio, [90])
        with self.assertRaises(ex.ErroDeExecucao) as e:
            ex.rodar_teste_final(rodar, self.raiz, "A", "b", limite)
        self.assertEqual((e.exception.causa, rodar.timeouts), ("caso", [80]))


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
