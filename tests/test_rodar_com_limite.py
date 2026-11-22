import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from agente_contrato.execucao import rodar_com_limite

PROCESSO_FALSO = Path(__file__).parent / "processo_falso.py"


def grupo_existe(pgid: int, espera_s: float = 2) -> bool:
    """Espera até `espera_s` o grupo sumir; o sistema leva um instante para recolher os mortos."""
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.05)
    return True


class TestRodarComLimite(unittest.TestCase):
    def test_termina_antes_do_limite(self):
        r = rodar_com_limite([sys.executable, str(PROCESSO_FALSO), "0.1"], limite_s=5)
        self.assertFalse(r.estourou_tempo)
        self.assertEqual(r.codigo_saida, 0)

    def test_estoura_o_limite_e_nao_deixa_ninguem_vivo(self):
        r = rodar_com_limite([sys.executable, str(PROCESSO_FALSO), "30", "--neto"], limite_s=0.5)
        self.assertTrue(r.estourou_tempo)
        self.assertIsNone(r.codigo_saida)
        pid_do_pai = int(r.saida.split()[1])  # a linha "pronto <pid>" que o falso imprime
        self.assertFalse(grupo_existe(pid_do_pai))


class TestInterrupcao(unittest.TestCase):
    def test_ctrl_c_nao_deixa_ninguem_vivo(self):
        # um Ctrl+C de verdade, enviado a este próprio processo meio segundo depois
        threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGINT)).start()
        with self.assertRaises(KeyboardInterrupt):
            rodar_com_limite([sys.executable, str(PROCESSO_FALSO), "30", "--neto"], limite_s=10)
        vivos = subprocess.run(["pgrep", "-f", f"{PROCESSO_FALSO} 30"], capture_output=True, text=True)
        self.assertEqual(vivos.stdout, "")


class TestBordaDoLimite(unittest.TestCase):
    def test_termina_quase_no_instante_do_limite(self):
        duracao = 0.3
        for folga in (-0.05, -0.02, -0.01, 0, 0.01, 0.02, 0.05):
            with self.subTest(folga=folga):
                r = rodar_com_limite([sys.executable, str(PROCESSO_FALSO), str(duracao), "--neto"],
                                     limite_s=duracao + folga)
                # na borda não dá para saber quem chega primeiro; os dois desfechos valem
                if r.estourou_tempo:
                    self.assertIsNone(r.codigo_saida)
                else:
                    self.assertEqual(r.codigo_saida, 0)
                pid_do_pai = int(r.saida.split()[1])
                self.assertFalse(grupo_existe(pid_do_pai))


if __name__ == "__main__":
    unittest.main()
