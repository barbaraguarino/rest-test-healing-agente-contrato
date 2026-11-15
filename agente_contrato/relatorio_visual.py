"""Relatório visual dos reparos (T52): uma página HTML por rodada, só com o que já está gravado.

Só LÊ a pasta da rodada (`resultados-agente1.json`, `comparacao.json` se existir, e `execucoes/<caso>-<rep>/`)
e o oráculo em `casos/`. Não roda Maven, não chama LLM, não altera nada em `resultados/`. A página sai
em `relatorios/<rodada>.html`, num arquivo só, sem internet (CSS embutido, sem JS, sem CDN).

Não mostra métricas agregadas nem conclusões: só o que aconteceu em cada execução.

Uso, na raiz do repositório:
    python -m agente_contrato.relatorio_visual --pasta resultados/t25-final
"""
import argparse
import html
import json
import sys
from pathlib import Path

TRATAMENTOS = ("baseline", "agentes", "agente_unico")
NOME_TRATAMENTO = {"baseline": "Baseline", "agentes": "Agentes", "agente_unico": "Agente único"}
ORACULOS = ("casos/oraculo-agente1-final.json", "casos/oraculo-agente1.json")
PENDENTE = "revisão manual pendente"


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def ler_json(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))


def ler_texto(caminho: Path) -> str | None:
    return caminho.read_text(encoding="utf-8") if caminho.is_file() else None


def nome_da_pasta(id_caso: str, tratamento: str, rep: int) -> str:
    meio = "" if tratamento == "agentes" else f"-{tratamento}"
    return f"{id_caso}{meio}-r{rep}"


def carregar_oraculo(raiz: Path) -> dict[str, dict]:
    """Junta os oráculos (final e piloto); o primeiro que tiver o caso vale. Lido só aqui, depois da execução."""
    casos: dict[str, dict] = {}
    for rel in ORACULOS:
        arq = raiz / rel
        if arq.is_file():
            for c in ler_json(arq)["casos"]:
                casos.setdefault(c["id_caso"], c)
    return casos


# ---------------------------------------------------------------- pedaços de HTML

def diff_html(texto: str | None, vazio: str) -> str:
    if not texto or not texto.strip():
        return f'<p class="vazio">{esc(vazio)}</p>'
    linhas = []
    for ln in texto.splitlines():
        if ln.startswith(("+++", "---", "diff ", "index ")):
            cl = "cab"
        elif ln.startswith("@@"):
            cl = "hunk"
        elif ln.startswith("+"):
            cl = "mais"
        elif ln.startswith("-"):
            cl = "menos"
        else:
            cl = "ctx"
        linhas.append(f'<span class="{cl}">{esc(ln)}</span>')
    return '<pre class="codigo">' + "\n".join(linhas) + "</pre>"


def codigo_html(texto: str | None, vazio: str) -> str:
    if texto is None:
        return f'<p class="vazio">{esc(vazio)}</p>'
    return f'<pre class="codigo">{esc(texto)}</pre>'


def caminho_html(caminho: list | None) -> str:
    if not caminho:
        return '<p class="vazio">Sem caminho (não houve laço de ferramentas).</p>'
    linhas = []
    for volta in caminho:
        nomes = []
        for f in volta.get("ferramentas", []):
            marca = ' <b class="err">(erro)</b>' if f.get("erro") else ""
            nomes.append(f'<code>{esc(f.get("nome"))}</code>{marca}')
        fim = " → <i>terminou</i>" if volta.get("terminou") else ""
        lista = ", ".join(nomes) if nomes else "—"
        linhas.append(
            f'<li><span class="etapa">{esc(volta.get("etapa"))} · volta {esc(volta.get("volta"))}</span> {lista}{fim}</li>')
    return '<ol class="caminho">' + "".join(linhas) + "</ol>"


def sim_nao(v) -> str:
    return "—" if v is None else ("sim" if v else "não")


def equivalencia(r: dict, comp: dict | None, sem_comparacao: bool) -> tuple[str, str]:
    """(texto, classe) do campo equivalente_oraculo."""
    eq = r.get("equivalente_oraculo")
    if eq is True:
        return "sim", "ok"
    if eq is False:
        return "não", "ruim"
    if r.get("decisao") != "reparar":
        return "— (não reparou)", "neutro"
    if r.get("rotulo_oraculo") == "legitima":
        return PENDENTE, "pend"
    return "— (sem correção esperada)", "neutro"


def ficha_html(r: dict, comp: dict | None, sem_comparacao: bool) -> str:
    eq_txt, eq_cl = equivalencia(r, comp, sem_comparacao)
    if comp:
        if comp.get("regra") is not None:
            regra = f"regra {comp['regra']}"
        elif r.get("decisao") == "reparar":
            regra = "nenhuma das regras 1 a 3"
        else:
            regra = "—"
        extra = ""
        if comp.get("motivos"):
            extra += "<div class='nota'>" + esc("; ".join(comp["motivos"])) + "</div>"
        if comp.get("revisao_manual"):
            extra += "<div class='nota'>Revisão manual: " + esc(comp["revisao_manual"]) + "</div>"
        if comp.get("veredito_manual") is not None:
            extra += ("<div class='nota'>Veredito manual: <b>" + esc(sim_nao(comp["veredito_manual"])) + "</b> — "
                      + esc(comp.get("motivo_do_veredito")) + "</div>")
    else:
        regra = "sem comparação nesta rodada" if sem_comparacao else "—"
        extra = ""
    campos = [
        ("decisão", esc(r.get("decisao")), "neutro"),
        ("compilou", sim_nao(r.get("compilou")), "neutro"),
        ("passou", sim_nao(r.get("passou")), "neutro"),
        ("erro", esc(r.get("erro")) if r.get("erro") else "nenhum", "neutro"),
        ("regra da D95", esc(regra), "neutro"),
        ("cenario_alterado", sim_nao(r.get("cenario_alterado")), "neutro"),
        ("equivalente_oraculo", esc(eq_txt), eq_cl),
    ]
    itens = "".join(f'<div class="campo {cl}"><span>{k}</span><b>{v}</b></div>' for k, v, cl in campos)
    return f'<div class="ficha">{itens}</div>{extra}'


def lista_recusas(recusas) -> str:
    if not recusas:
        return ""
    itens = "".join(
        "<li>" + esc(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) + "</li>" for x in recusas)
    return f'<div class="recusa"><b>O guarda recusou:</b><ul>{itens}</ul></div>'


def execucao_html(r: dict, pasta: Path, comp: dict | None, sem_comparacao: bool, caso: dict) -> str:
    log = ler_json(pasta / "log.json") if (pasta / "log.json").is_file() else {}
    rep = r.get("repeticao")
    nao_reparou = r.get("decisao") != "reparar"
    regressao = caso.get("rotulo_oraculo") != "legitima"
    aviso = ""
    if nao_reparou:
        aviso = '<div class="aviso">O agente <b>não reparou</b> este teste.</div>'
    just = log.get("justificativa")
    texto_just = f'<p class="just"><b>Justificativa gravada:</b> {esc(just)}</p>' if just else ""
    detalhe = log.get("detalhe")
    texto_det = f'<p class="just"><b>Detalhe:</b> {esc(detalhe)}</p>' if detalhe else ""
    causa = log.get("causa")
    texto_causa = f'<p class="just"><b>Causa:</b> {esc(causa)}</p>' if causa else ""
    reparo = ler_texto(pasta / "reparo.diff")
    depois = ler_texto(pasta / "depois.java")
    cam = ler_json(pasta / "caminho.json") if (pasta / "caminho.json").is_file() else None
    if r.get("tratamento") == "baseline":
        aplicadas = log.get("aplicadas") or []
        cam_html = ("<p class='vazio'>Baseline: sem laço de ferramentas, sem caminho.</p>")
        if aplicadas:
            cam_html += "<p><b>Mudanças aplicadas:</b></p><ul>" + "".join(f"<li>{esc(a)}</li>" for a in aplicadas) + "</ul>"
        ign = log.get("ignoradas") or []
        if ign:
            cam_html += "<p><b>Ignoradas:</b></p><ul>" + "".join(f"<li>{esc(a)}</li>" for a in ign) + "</ul>"
    else:
        cam_html = caminho_html(cam)
    vazio_reparo = "O agente não reparou: não há diff." if nao_reparou else "Sem diff gravado."
    corpo = (
        aviso + ficha_html(r, comp, sem_comparacao) + lista_recusas(log.get("recusas_do_guarda"))
        + texto_just + texto_det + texto_causa
        + '<details open><summary>Reparo (diff)</summary>' + diff_html(reparo, vazio_reparo) + '</details>'
        + '<details><summary>Teste depois (depois.java)</summary>'
        + codigo_html(depois, "Sem depois.java.") + '</details>'
        + '<details><summary>Caminho</summary>' + cam_html + '</details>'
    )
    marca = " regressao" if regressao else ""
    return f'<section class="exec{marca}"><h4>repetição {esc(rep)}</h4>{corpo}</section>'


def caso_html(caso: dict, execs: list[dict], raiz_rodada: Path, comps: dict, sem_comparacao: bool,
              raiz_repo: Path) -> str:
    idc = caso["id_caso"]
    legit = caso.get("rotulo_oraculo") == "legitima"
    selo = ('<span class="selo legitima">legítima</span>' if legit
            else '<span class="selo real">problema real (regressão)</span>')
    primeira = next((e for e in execs if e["id_caso"] == idc), None)
    antes = None
    for e in execs:
        if e["id_caso"] == idc:
            antes = ler_texto(raiz_rodada / "execucoes" / nome_da_pasta(idc, e["tratamento"], e["repeticao"]) / "antes.java")
            if antes:
                break
    if legit and caso.get("correcao_esperada"):
        esperado = diff_html(ler_texto(raiz_repo / caso["correcao_esperada"]), "Patch esperado não encontrado.")
    else:
        esperado = ('<p class="vazio">Sem correção esperada: o teste está certo e o código é que se afastou do '
                    'contrato (oráculo: problema real). O esperado é <b>não reparar</b>.</p>')
    topo = (f'<div class="lado"><div class="col"><h4>Teste antes</h4>{codigo_html(antes, "Sem antes.java.")}</div>'
            f'<div class="col"><h4>Correção esperada (oráculo)</h4>{esperado}</div></div>')
    blocos = []
    for t in TRATAMENTOS:
        doT = sorted((e for e in execs if e["id_caso"] == idc and e["tratamento"] == t), key=lambda e: e["repeticao"])
        existe_na_rodada = any(e["tratamento"] == t for e in execs)
        if not doT:
            msg = "não sorteado para este caso" if existe_na_rodada else "não rodado nesta rodada"
            blocos.append(f'<div class="trat vazio-trat"><h3>{NOME_TRATAMENTO[t]}</h3><p class="vazio">{msg}.</p></div>')
            continue
        cols = "".join(
            execucao_html(e, raiz_rodada / "execucoes" / nome_da_pasta(idc, t, e["repeticao"]),
                          comps.get((idc, t, e["repeticao"])), sem_comparacao, caso) for e in doT)
        blocos.append(f'<div class="trat"><h3>{NOME_TRATAMENTO[t]}</h3><div class="execs">{cols}</div></div>')
    return (f'<article class="caso" id="{esc(idc)}"><h2>{esc(idc)} <small>{esc(caso.get("categoria"))} · '
            f'{esc(caso.get("lado"))}</small> {selo}</h2>'
            f'<p class="teste">Teste afetado: <code>{esc(caso.get("teste_afetado"))}</code></p>'
            f'{topo}{"".join(blocos)}</article>')


def indice_html(casos: list[dict], execs: list[dict]) -> str:
    itens = []
    for c in casos:
        pontos = ""
        for t in TRATAMENTOS:
            n = sum(1 for e in execs if e["id_caso"] == c["id_caso"] and e["tratamento"] == t)
            pontos += f'<i class="ponto {"on" if n else "off"}" title="{NOME_TRATAMENTO[t]}: {n}"></i>'
        itens.append(f'<a href="#{esc(c["id_caso"])}">{esc(c["id_caso"])} {pontos}</a>')
    return '<nav class="indice">' + "".join(itens) + "</nav>"


CSS = """
:root{--bg:#f6f7f9;--fg:#1c2330;--card:#fff;--bd:#d5d9e0;--mut:#5d6675;--mais:#d7f5dd;--menos:#fadadd;--hunk:#e3e8f5;
--ok:#1e7a3a;--ruim:#b3261e;--pend:#9a5b00;--pendbg:#fff1d6}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ee;--card:#1d2128;--bd:#343b46;--mut:#9aa4b2;
--mais:#173a22;--menos:#4a1d22;--hunk:#222b3f;--ok:#6fd58a;--ruim:#ff8a80;--pend:#ffc766;--pendbg:#3d3012}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header,main{max-width:1280px;margin:0 auto;padding:12px 16px}
h1{font-size:1.4rem;margin:.3em 0}h2{font-size:1.15rem;margin:.2em 0}h3{font-size:1.05rem;margin:.2em 0}h4{margin:.2em 0;font-size:.95rem}
small{color:var(--mut);font-weight:400}.mut{color:var(--mut)}
.indice{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.indice a{border:1px solid var(--bd);background:var(--card);padding:4px 8px;border-radius:6px;color:inherit;text-decoration:none;font-size:.85rem}
.ponto{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:3px}
.ponto.on{background:var(--ok)}.ponto.off{background:var(--bd)}
.caso{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px;margin:16px 0}
.selo{font-size:.75rem;padding:2px 8px;border-radius:10px;vertical-align:middle;border:1px solid var(--bd)}
.selo.real{background:var(--pendbg);color:var(--pend)}
.lado{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.col,.exec{min-width:0}
.execs{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.trat{border-top:2px solid var(--bd);margin-top:14px;padding-top:6px}
.exec{border:1px solid var(--bd);border-radius:8px;padding:8px}
.exec.regressao{border-left:4px solid var(--pend)}
pre.codigo{margin:4px 0;padding:8px;background:var(--bg);border:1px solid var(--bd);border-radius:6px;overflow-x:auto;
font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre;max-height:420px;overflow-y:auto}
pre.codigo span{display:inline-block;min-width:100%}
.mais{background:var(--mais)}.menos{background:var(--menos)}.hunk{background:var(--hunk);color:var(--mut)}.cab{color:var(--mut)}
.ficha{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;margin:6px 0}
.campo{border:1px solid var(--bd);border-radius:6px;padding:4px 6px;font-size:.85rem;min-width:0;overflow-wrap:anywhere}
.campo span{display:block;color:var(--mut);font-size:.72rem}.campo.ok b{color:var(--ok)}.campo.ruim b{color:var(--ruim)}
.campo.pend{background:var(--pendbg)}.campo.pend b{color:var(--pend)}
.nota{font-size:.82rem;color:var(--mut);margin:2px 0}
.aviso{background:var(--pendbg);color:var(--pend);padding:6px 8px;border-radius:6px;margin:6px 0}
.recusa{background:var(--menos);padding:6px 8px;border-radius:6px;margin:6px 0;font-size:.88rem}
.just{font-size:.88rem;margin:6px 0}
.vazio{color:var(--mut);font-style:italic;margin:4px 0}
.caminho{margin:4px 0;padding-left:20px;font-size:.85rem}.etapa{color:var(--mut)}.err{color:var(--ruim)}
summary{cursor:pointer;font-weight:600;font-size:.9rem;margin:6px 0}
code{font:12.5px ui-monospace,Menlo,Consolas,monospace;overflow-wrap:anywhere}
@media (max-width:700px){.lado{grid-template-columns:1fr}.execs{grid-template-columns:1fr}}
"""


def gerar(pasta: Path, raiz_repo: Path) -> str:
    resultados = ler_json(pasta / "resultados-agente1.json")
    execs = resultados["execucoes"]
    arq_comp = pasta / "comparacao.json"
    comp_json = ler_json(arq_comp) if arq_comp.is_file() else None
    sem_comparacao = comp_json is None
    comps = {}
    if comp_json:
        for c in comp_json["execucoes"]:
            comps[(c["id_caso"], c["tratamento"], c["repeticao"])] = c
    oraculo = carregar_oraculo(raiz_repo)
    ids = sorted({e["id_caso"] for e in execs})
    faltando = [i for i in ids if i not in oraculo]
    if faltando:
        raise SystemExit(f"Casos sem oráculo em casos/: {', '.join(faltando)}")
    casos = [oraculo[i] for i in ids]
    nota_comp = ("Esta rodada não tem <code>comparacao.json</code>: regra da D95 e equivalência não foram calculadas."
                 if sem_comparacao else "Regra da D95 e motivos vêm do <code>comparacao.json</code> da rodada.")
    corpo = "".join(caso_html(c, execs, pasta, comps, sem_comparacao, raiz_repo) for c in casos)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Relatório visual — {esc(pasta.name)}</title><style>{CSS}</style></head><body>'
        f'<header><h1>Relatório visual dos reparos — {esc(pasta.name)}</h1>'
        f'<p class="mut">Gerado só a partir dos arquivos gravados em <code>resultados/{esc(pasta.name)}</code>; nada foi rodado. '
        f'API: <code>{esc(resultados.get("versao_api"))}</code>. {nota_comp} '
        f'O oráculo foi lido só agora, depois da execução. {len(casos)} casos, {len(execs)} execuções.</p>'
        f'{indice_html(casos, execs)}</header><main>{corpo}</main></body></html>'
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gera a página HTML dos reparos de uma rodada (só lê).")
    ap.add_argument("--pasta", required=True, help="pasta da rodada, ex.: resultados/t25-final")
    ap.add_argument("--saida", help="arquivo HTML de saída (padrão: relatorios/<rodada>.html)")
    a = ap.parse_args(argv)
    raiz = Path.cwd().resolve()
    pasta = Path(a.pasta).resolve()
    saida = Path(a.saida).resolve() if a.saida else raiz / "relatorios" / f"{pasta.name}.html"
    if (raiz / "resultados").resolve() in (saida, *saida.parents):
        print("A saída não pode ficar dentro de resultados/.", file=sys.stderr)
        return 2
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(gerar(pasta, raiz), encoding="utf-8")
    print(f"Página gravada em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
