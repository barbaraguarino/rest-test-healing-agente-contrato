"""Roda processos externos (o Maven) com limite de tempo (T23b, D111, D118)."""
import os
import signal
import subprocess

ESPERA_DO_SIGTERM_S = 5


def encerrar_grupo(proc: subprocess.Popen) -> None:
    """Encerra o processo e tudo o que ele abriu, tolerando quem já terminou sozinho."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(ESPERA_DO_SIGTERM_S)
        except subprocess.TimeoutExpired:
            pass
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
