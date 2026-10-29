"""Relógio do caso (T23c, D111(b), D118): 180 s a partir do Maven inicial, sem contar a espera do LLM."""
import time
from contextlib import contextmanager

LIMITE_CASO_S = 180  # D111(b)


class RelogioCaso:
    """Relógio de xadrez: corre enquanto o código trabalha e pausa enquanto o modelo responde.

    Quem chama o laço cria o relógio logo depois do Maven inicial, quando o agente recebe a falha (D118).
    `agora` é injetável para os testes usarem um relógio falso, sem esperar de verdade.
    """

    def __init__(self, limite_s: float = LIMITE_CASO_S, agora=time.monotonic):
        self.limite_s = limite_s
        self._agora = agora
        self._inicio = agora()
        self._pausado_s = 0.0

    @contextmanager
    def esperando_llm(self):
        """Pausa o relógio durante a chamada ao modelo (D111(b))."""
        comeco = self._agora()
        try:
            yield
        finally:
            self._pausado_s += self._agora() - comeco

    def gasto(self) -> float:
        return self._agora() - self._inicio - self._pausado_s

    def restante(self) -> float:
        return max(0.0, self.limite_s - self.gasto())

    def estourou(self) -> bool:
        return self.restante() == 0

