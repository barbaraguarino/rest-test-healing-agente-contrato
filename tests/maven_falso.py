"""Maven falso, no lugar do mvnw nos testes de rodar_teste (T23b).

Roda na pasta da cópia e imita o que o Maven deixa: o texto na tela, o código de saída e a
súmula em target/surefire-reports. O modo diz o desfecho.
"""
import sys
import time
from pathlib import Path

SUMULA = ('<testsuite name="ApiTest" tests="{tests}" failures="{failures}" errors="0" '
          'skipped="0" time="2.5"></testsuite>')


def escrever_sumula(tests: int, failures: int) -> None:
    pasta = Path("target") / "surefire-reports"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "TEST-ApiTest.xml").write_text(SUMULA.format(tests=tests, failures=failures))


def main() -> None:
    modo = sys.argv[1]
    if modo == "passa":
        escrever_sumula(1, 0)
        print("BUILD SUCCESS")
    elif modo == "falha":
        escrever_sumula(1, 1)
        print("BUILD FAILURE")
        sys.exit(1)
    elif modo == "nao_compila":
        print("[ERROR] COMPILATION ERROR")
        sys.exit(1)
    elif modo == "zero_testes":
        escrever_sumula(0, 0)
        print("BUILD SUCCESS")
    elif modo == "lento":
        time.sleep(30)


if __name__ == "__main__":
    main()
