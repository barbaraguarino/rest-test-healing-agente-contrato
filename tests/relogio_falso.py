"""Dublê do time.monotonic para os testes do relógio do caso e do laço."""


class RelogioFalso:
    """Substitui o time.monotonic: o tempo só anda quando o teste manda."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def andar(self, segundos: float) -> None:
        self.t += segundos
