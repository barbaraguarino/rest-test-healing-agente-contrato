import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path

from agente_contrato.execucao import encerrar_grupo

PROCESSO_FALSO = Path(__file__).parent / "processo_falso.py"


class TestProvocarProcessLookupError(unittest.TestCase):
    def test_killpg_em_grupo_que_ja_acabou_levanta_erro(self):
        proc = subprocess.Popen([sys.executable, str(PROCESSO_FALSO), "0.1"],
                                start_new_session=True)
        proc.wait()
        with self.assertRaises(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)


class TestEncerrarGrupo(unittest.TestCase):
    def test_encerra_o_processo_e_o_neto(self):
        proc = subprocess.Popen([sys.executable, str(PROCESSO_FALSO), "30", "--neto"],
                                stdout=subprocess.PIPE, text=True, start_new_session=True)
        proc.stdout.readline()  # espera o "pronto": o neto já foi aberto
        encerrar_grupo(proc)
        proc.stdout.close()
        with self.assertRaises(ProcessLookupError):
            os.killpg(proc.pid, 0)  # sinal 0 só pergunta se o grupo existe


if __name__ == "__main__":
    unittest.main()
