"""Compara dois ensaios da baseline (T51): só o tempo_s pode mudar (D133). Sem LLM e sem Maven.

Confere, caso a caso, os campos do resultado (menos o tempo_s) e os arquivos antes.java, depois.java e
reparo.diff de cada execução. Termina com código 1 se aparecer outra diferença.

Uso, na raiz do repositório: python -m tests.comparar_ensaios resultados/t51-ensaio resultados/t51-ensaio-d133
"""
import json
import sys
from pathlib import Path

a, b = Path(sys.argv[1]), Path(sys.argv[2])
ra = {r["id_caso"]: r for r in json.loads((a / "resultados-agente1.json").read_text())["execucoes"]}
rb = {r["id_caso"]: r for r in json.loads((b / "resultados-agente1.json").read_text())["execucoes"]}
ok = ra.keys() == rb.keys()
for i in sorted(ra):
    dif = sorted(k for k in ra[i] if k != "tempo_s" and ra[i][k] != rb[i][k])
    arq = [n for n in ("antes.java", "depois.java", "reparo.diff")
           if (a / "execucoes" / f"{i}-baseline-r1" / n).read_text() != (b / "execucoes" / f"{i}-baseline-r1" / n).read_text()]
    ok = ok and not dif and not arq
    print(f"{i} tempo_s {ra[i]['tempo_s']:>8} -> {rb[i]['tempo_s']:>8} | outros campos: {dif or 'iguais'} | arquivos: {arq or 'iguais'}")
print("SÓ O tempo_s MUDOU" if ok else "OUTRA DIFERENÇA")
sys.exit(0 if ok else 1)
