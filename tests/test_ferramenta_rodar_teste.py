import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import ErroDeExecucao, ResultadoTeste
from agente_contrato.ferramentas import rodar_teste
from agente_contrato.laco import ErroDeFerramenta
from agente_contrato.relogio import RelogioCaso
from tests.relogio_falso import RelogioFalso

PASSOU = ResultadoTeste(True, True, 12.0, 6.0)
FALHOU = ResultadoTeste(True, False, 12.0, 6.0)
NAO_COMPILOU = ResultadoTeste(False, False, 8.0, 0.0)

FALHA_XML = ('<testsuite tests="1"><testcase name="m"><failure type="java.lang.AssertionError" '
             'message="No value at JSON path &quot;$.descricao&quot;"/></testcase></testsuite>')


class MavenFalso:
    """No lugar de execucao.rodar_teste: guarda o limite recebido e devolve o desfecho dado."""

    def __init__(self, desfecho, relatorio: str | None = None):
        self.desfecho, self.relatorio = desfecho, relatorio
        self.limite_s = None

    def __call__(self, raiz, classe, metodo, limite_s):
        self.limite_s = limite_s
        if self.relatorio:  # o Surefire escreve o relatório na cópia
            pasta = raiz / "target" / "surefire-reports"
            pasta.mkdir(parents=True)
            (pasta / f"TEST-{classe}.xml").write_text(self.relatorio)
        if isinstance(self.desfecho, Exception):
            raise self.desfecho
        return self.desfecho


class TestRodarTeste(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.agora = RelogioFalso()
        self.relogio = RelogioCaso(agora=self.agora)

    def rodar(self, maven):
        return rodar_teste(maven, self.raiz, "ProdutoTest", "lista", self.relogio)

    def test_passou(self):
        self.assertEqual(self.rodar(MavenFalso(PASSOU)), "O teste passou.")

    def test_nao_compilou(self):
        self.assertEqual(self.rodar(MavenFalso(NAO_COMPILOU)), "O teste não compilou.")

    def test_falhou_traz_a_mensagem_do_surefire(self):
        self.assertEqual(self.rodar(MavenFalso(FALHOU, FALHA_XML)),
                         'O teste falhou.\nfailure java.lang.AssertionError: No value at JSON path "$.descricao"')

    def test_nao_passou_sem_mensagem_de_falha(self):
        # ex.: o teste foi ignorado (@Disabled)
        self.assertEqual(self.rodar(MavenFalso(FALHOU)),
                         "O teste não passou, e o relatório não traz mensagem de falha.")

    def test_estouro_volta_ao_modelo_como_erro(self):
        with self.assertRaisesRegex(ErroDeFerramenta, "passou de 120 s"):
            self.rodar(MavenFalso(ErroDeExecucao("passou de 120s", "timeout")))

    def test_erro_de_infraestrutura_para_o_caso(self):
        with self.assertRaises(ErroDeExecucao):
            self.rodar(MavenFalso(ErroDeExecucao("2 testes executados, esperado 1")))

    def test_limite_e_o_que_resta_do_caso(self):
        self.agora.andar(150)  # restam 30 s dos 180 s do caso
        maven = MavenFalso(PASSOU)
        self.rodar(maven)
        self.assertEqual(maven.limite_s, 30)


if __name__ == "__main__":
    unittest.main()
