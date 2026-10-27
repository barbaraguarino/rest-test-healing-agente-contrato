"""Roda processos externos (o Maven) com limite de tempo (T23b, D111, D118)."""
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

ESPERA_DO_SIGTERM_S = 5


@dataclass
class ResultadoProcesso:
    codigo_saida: int | None  # None quando o tempo estourou
    saida: str
    estourou_tempo: bool


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


def rodar_com_limite(comando: list[str], limite_s: float, cwd: Path | None = None) -> ResultadoProcesso:
    """Roda o comando e, se passar de `limite_s`, encerra o processo e os filhos."""
    proc = subprocess.Popen(comando, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    try:
        saida, _ = proc.communicate(timeout=limite_s)
    except subprocess.TimeoutExpired:
        encerrar_grupo(proc)
        saida, _ = proc.communicate()
        return ResultadoProcesso(None, saida, True)
    return ResultadoProcesso(proc.returncode, saida, False)
