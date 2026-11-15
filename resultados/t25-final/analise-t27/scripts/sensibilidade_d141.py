"""T27, EXPLORATÓRIO: copia o resultados-agente1.json para DESTINO e troca o
equivalente_oraculo do A1-027 dos agentes nas repetições 1 e 3 (veredito manual da D141)
de true para false. O arquivo oficial não é aberto para escrita.
Uso: python -I sensibilidade_d141.py ORIGEM DESTINO"""
import json, sys
from pathlib import Path
origem, destino = Path(sys.argv[1]), Path(sys.argv[2])
assert origem.resolve() != destino.resolve()
dados = json.loads(origem.read_text(encoding="utf-8"))
trocados = []
for r in dados["execucoes"]:
    if r["id_caso"] == "A1-027" and r["tratamento"] == "agentes" and r["repeticao"] in (1, 3):
        assert r["equivalente_oraculo"] is True, r
        r["equivalente_oraculo"] = False
        trocados.append(r["repeticao"])
assert sorted(trocados) == [1, 3], trocados
destino.parent.mkdir(parents=True, exist_ok=True)
destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"cópia gravada em {destino}; A1-027 agentes r{trocados} -> equivalente_oraculo=false")
