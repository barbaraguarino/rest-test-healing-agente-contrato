import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import (ErroDeExecucao, ResultadoTeste, rodar_teste_final,
                                      rodar_teste_inicial)

PASSOU = ResultadoTeste(True, True, 12.0, 6.0)


class RodarFalso:
    """No lugar de rodar_teste: devolve, em ordem, um resultado ou um erro a cada chamada."""

    def __init__(self, *desfechos):
        self.desfechos = list(desfechos)
        self.chamadas = 0

    def __call__(self, raiz, classe, metodo, limite_s):
        self.chamadas += 1
        desfecho = self.desfechos.pop(0)
        if isinstance(desfecho, Exception):
            raise desfecho
        return desfecho


def estouro() -> ErroDeExecucao:
    return ErroDeExecucao("passou de 120s", "timeout")


class TestMavenInicial(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sem_estouro_roda_uma_vez(self):
        rodar = RodarFalso(PASSOU)
        self.assertEqual(rodar_teste_inicial(rodar, self.raiz, "A", "m"), (PASSOU, 1))

    def test_um_estouro_roda_de_novo_sem_o_target(self):
        (self.raiz / "target").mkdir()
        rodar = RodarFalso(estouro(), PASSOU)
        self.assertEqual(rodar_teste_inicial(rodar, self.raiz, "A", "m"), (PASSOU, 2))
        self.assertFalse((self.raiz / "target").exists())

    def test_dois_estouros_viram_erro_execucao_fora_das_metricas(self):
        rodar = RodarFalso(estouro(), estouro())
        with self.assertRaises(ErroDeExecucao) as ctx:
            rodar_teste_inicial(rodar, self.raiz, "A", "m")
        self.assertEqual((ctx.exception.codigo, ctx.exception.causa),
                         ("erro_execucao", "estouro_maven_inicial"))
        self.assertEqual(rodar.chamadas, 2)

    def test_outro_erro_nao_se_repete(self):
        rodar = RodarFalso(ErroDeExecucao("0 testes executados"))
        with self.assertRaises(ErroDeExecucao):
            rodar_teste_inicial(rodar, self.raiz, "A", "m")
        self.assertEqual(rodar.chamadas, 1)


class TestMavenFinal(unittest.TestCase):
    def test_sem_estouro_devolve_o_resultado(self):
        self.assertEqual(rodar_teste_final(RodarFalso(PASSOU), Path("."), "A", "m"), PASSOU)

    def test_estouro_e_timeout_sem_reexecucao(self):
        rodar = RodarFalso(estouro(), PASSOU)
        with self.assertRaises(ErroDeExecucao) as ctx:
            rodar_teste_final(rodar, Path("."), "A", "m")
        self.assertEqual((ctx.exception.codigo, ctx.exception.causa), ("timeout", "teste_final"))
        self.assertEqual(rodar.chamadas, 1)


if __name__ == "__main__":
    unittest.main()
