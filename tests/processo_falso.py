"""Processo falso e lento, no lugar do Maven nos testes de timeout (T23b)."""
import subprocess
import sys
import time


def main() -> None:
    duracao = float(sys.argv[1])
    if "--neto" in sys.argv:
        subprocess.Popen([sys.executable, __file__, str(duracao)])
        print("pronto", flush=True)
    time.sleep(duracao)


if __name__ == "__main__":
    main()
