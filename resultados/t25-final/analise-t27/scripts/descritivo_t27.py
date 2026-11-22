"""T27 (descritivo): totais de tempo, tokens e custo por tratamento e variação entre
repetições por caso. Só lê os arquivos gravados; não muda nada.
Uso: python -I descritivo_t27.py PASTA_DA_RODADA [--json SAIDA]"""
import json, sys
from collections import defaultdict
from pathlib import Path

pasta = Path(sys.argv[1])
execs = json.loads((pasta / "resultados-agente1.json").read_text(encoding="utf-8"))["execucoes"]
chamadas = [json.loads(l) for l in (pasta / "chamadas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

saida = {"rodada": str(pasta), "totais_por_tratamento": {}, "chamadas_por_tratamento": {}, "variacao_entre_repeticoes": []}
por_trat = defaultdict(list)
for r in execs:
    por_trat[r["tratamento"]].append(r)
print("TOTAIS POR TRATAMENTO (somados de resultados-agente1.json)")
print(f"  {'tratamento':<14}{'execucoes':>10}{'casos':>7}{'tempo_s':>12}{'tokens':>11}{'custo_usd':>12}")
for t, L in sorted(por_trat.items()):
    tot = {"execucoes": len(L), "casos": len({r['id_caso'] for r in L}),
           "tempo_s": round(sum(r["tempo_s"] for r in L), 4),
           "tokens": sum(r["tokens"] for r in L),
           "custo_usd": round(sum(r["custo_usd"] for r in L), 7)}
    saida["totais_por_tratamento"][t] = tot
    print(f"  {t:<14}{tot['execucoes']:>10}{tot['casos']:>7}{tot['tempo_s']:>12.1f}{tot['tokens']:>11}{tot['custo_usd']:>12.6f}")

print("\nCHAMADAS AO LLM (chamadas.jsonl; linha sem 'tratamento' é dos agentes, T49)")
cp = defaultdict(lambda: {"chamadas": 0, "input_tokens": 0, "output_tokens": 0, "custo_usd": 0.0})
for c in chamadas:
    t = c.get("tratamento") or "agentes"
    cp[t]["chamadas"] += 1
    cp[t]["input_tokens"] += c.get("input_tokens") or 0
    cp[t]["output_tokens"] += c.get("output_tokens") or 0
    cp[t]["custo_usd"] += c.get("custo_usd") or 0
for t, v in sorted(cp.items()):
    v["custo_usd"] = round(v["custo_usd"], 7)
    saida["chamadas_por_tratamento"][t] = v
    print(f"  {t:<14} chamadas={v['chamadas']}  entrada={v['input_tokens']}  saida={v['output_tokens']}  custo_usd={v['custo_usd']:.6f}")
tot = sum(v["custo_usd"] for v in cp.values())
saida["custo_total_usd"] = round(tot, 7)
print(f"  total custo_usd={tot:.6f}  chamadas={sum(v['chamadas'] for v in cp.values())}")

print("\nVARIAÇÃO ENTRE AS 3 REPETIÇÕES (casos em que algum resultado binário não foi unânime)")
campos = ["decisao", "passou", "equivalente_oraculo", "cenario_alterado"]
grupos = defaultdict(list)
for r in execs:
    if r["tratamento"] != "baseline":
        grupos[(r["tratamento"], r["id_caso"])].append(r)
unanimes = defaultdict(int)
for (t, c), L in sorted(grupos.items()):
    L.sort(key=lambda r: r["repeticao"])
    dif = {k: [r[k] for r in L] for k in campos if len({json.dumps(r[k]) for r in L}) > 1}
    if dif:
        item = {"tratamento": t, "id_caso": c, "categoria": L[0]["categoria"], "rotulo_oraculo": L[0]["rotulo_oraculo"], "por_repeticao": dif}
        saida["variacao_entre_repeticoes"].append(item)
        print(f"  {t:<13}{c}  {L[0]['categoria']:<24}{L[0]['rotulo_oraculo']:<14}{dif}")
    else:
        unanimes[t] += 1
for t in sorted({t for t, _ in grupos}):
    n = len({c for tt, c in grupos if tt == t})
    saida.setdefault("unanimes", {})[t] = {"unanimes": unanimes[t], "casos": n}
    print(f"  {t}: {unanimes[t]} de {n} casos unânimes nos 4 campos")

if "--json" in sys.argv:
    Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
