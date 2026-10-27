import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path

PROCESSO_FALSO = Path(__file__).parent / "processo_falso.py"


class TestProvocarProcessLookupError(unittest.TestCase):
    def test_killpg_em_grupo_que_ja_acabou_levanta_erro(self):
        proc = subprocess.Popen([sys.executable, str(PROCESSO_FALSO), "0.1"],
                                start_new_session=True)
        proc.wait()
        with self.assertRaises(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
