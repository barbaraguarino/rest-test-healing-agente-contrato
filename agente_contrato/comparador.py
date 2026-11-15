"""Comparação do reparo com a correção esperada do oráculo (T50; D80, D95, D109, D110, D119).

Código determinístico, sem LLM e sem Maven: igual ao da v1 (tag `rodada-2`), sobre o `teste_java.py` e o
`contrato.py` da develop. Só roda depois da execução, porque lê o oráculo. Uma regra que não consegue
decidir devolve None: o caso vai para a revisão manual (D80), nunca é adivinhado.

Novo na T50: `Comparacao.regra` diz qual regra da D95 deu a equivalência (1, 2 ou 3), e `revisao_manual`
traz para cá o critério da D80 e da D109, que na v1 ficava no `rodar_baseline`.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass

from . import contrato as c
from . import teste_java as tj


@dataclass(frozen=True)
class Comparacao:
    equivalente: bool | None       # None: sem correção esperada ou a regra não decide
    cenario_alterado: bool | None  # None: a regra não decide
    motivos: tuple[str, ...]
    regra: int | None = None       # a regra da D95 que deu a equivalência (1, 2 ou 3); None se não deu


# ---------------------------------------------------------------- extração

def _sem_espacos(texto: str) -> str:
    return re.sub(r"\s+", "", texto)


@dataclass(frozen=True)
class _Chamada:
    http: str
    url: str
    rota: str | None
    status: int | None
    corpo: object | None
    assercoes: tuple[tuple[str, str], ...]  # (caminho da expressão, asserção sem espaços)


@dataclass(frozen=True)
class _Metodo:
    fora: str  # o arquivo sem o corpo do método afetado
    corpo: str
    chamadas: tuple[_Chamada, ...]


def _texto_da_asserção(texto: str, a: tj.Assercao) -> str:
    """O `.andExpect(...)` que contém a asserção, de `.andExpect(` até o parêntese que o fecha.

    Não depende de quebras de linha: um método reescrito pelo LLM com o corpo numa linha só
    tem as mesmas asserções que o original (T09, etapa 3, A1-001). Sem `.andExpect(` antes da
    asserção, volta ao texto da linha inteira.
    """
    ini = texto.rfind(".andExpect(", 0, a.ini_expressao)
    if ini >= 0:
        i, nivel = ini + len(".andExpect"), 0
        while i < len(texto):
            proximo = tj._depois_do_literal(texto, i)
            if proximo != i:
                i = proximo
                continue
            if texto[i] == "(":
                nivel += 1
            elif texto[i] == ")":
                nivel -= 1
                if nivel == 0:
                    return texto[ini:i + 1]
            i += 1
    return texto[a.ini_linha:a.fim_linha]


def _extrair(texto: str, nome: str, rotas: dict[str, set[str]]) -> _Metodo:
    metodo = tj.localizar_metodo(texto, nome)
    chamadas = []
    for ch in tj.analisar_chamadas(texto, metodo, rotas):
        corpo = None
        if ch.corpo is not None:
            try:
                corpo = json.loads(texto[ch.corpo.ini:ch.corpo.fim])
            except json.JSONDecodeError as e:
                raise tj.ErroDeAnalise(f"corpo JSON inválido: {e}") from None
        assercoes = tuple((tj.caminho_da_expressao(a.expressao),
                           _sem_espacos(_texto_da_asserção(texto, a)).rstrip(";"))
                          for a in ch.assercoes)
        chamadas.append(_Chamada(ch.metodo_http, ch.url, ch.rota, ch.status_esperado, corpo, assercoes))
    return _Metodo(texto[:metodo.inicio] + texto[metodo.fim:], texto[metodo.inicio:metodo.fim],
                   tuple(chamadas))


# ---------------------------------------------------------------- JSON

def _partes(caminho: str) -> list[str]:
    return re.findall(r"\[\]|[^.\[\]]+", caminho)


def _remover(obj, partes: list[str]):
    """Cópia de `obj` sem o campo que o caminho designa."""
    if not partes:
        return obj
    parte, resto = partes[0], partes[1:]
    if parte == "[]":
        return [_remover(e, resto) for e in obj] if isinstance(obj, list) else obj
    if not isinstance(obj, dict):
        return obj
    if not resto:
        return {k: v for k, v in obj.items() if k != parte}
    return {k: (_remover(v, resto) if k == parte else v) for k, v in obj.items()}


def _valores(obj, partes: list[str]) -> list:
    if not partes:
        return [obj]
    parte, resto = partes[0], partes[1:]
    if parte == "[]":
        return [v for e in obj for v in _valores(e, resto)] if isinstance(obj, list) else []
    return _valores(obj[parte], resto) if isinstance(obj, dict) and parte in obj else []


def _do_tipo(valor, p: c.Propriedade) -> bool:
    if p.enum:
        return valor in p.enum
    return {"string": isinstance(valor, str),
            "integer": isinstance(valor, int) and not isinstance(valor, bool),
            "number": isinstance(valor, (int, float)) and not isinstance(valor, bool),
            "boolean": isinstance(valor, bool),
            "array": isinstance(valor, list), "object": isinstance(valor, dict)}.get(p.tipo, False)


def _folhas(valor, prefixo: str = "") -> Counter:
    if isinstance(valor, dict) and valor:
        folhas = Counter()
        for k, v in valor.items():
            folhas += _folhas(v, f"{prefixo}.{k}" if prefixo else k)
        return folhas
    if isinstance(valor, list) and valor:
        folhas = Counter()
        for v in valor:
            folhas += _folhas(v, prefixo + "[]")
        return folhas
    return Counter({(prefixo, json.dumps(valor, sort_keys=True)): 1})


def _debaixo(cam: str, base: str) -> bool:
    return cam == base or cam.startswith(base + ".") or cam.startswith(base + "[]")


# ---------------------------------------------------------------- equivalência (D95)

def _regra_2(a: _Metodo, b: _Metodo, ignorar: list[str] | None = None) -> bool:
    if len(a.chamadas) != len(b.chamadas):
        return False
    for x, y in zip(a.chamadas, b.chamadas):
        if (x.http, x.url, x.status) != (y.http, y.url, y.status):
            return False
        cx, cy = x.corpo, y.corpo
        for caminho in ignorar or ():
            cx, cy = _remover(cx, _partes(caminho)), _remover(cy, _partes(caminho))
        if cx != cy or sorted(x.assercoes) != sorted(y.assercoes):
            return False
    return True


def _regra_3(reparado: _Metodo, esperado: _Metodo, mudancas: list[c.Mudanca]) -> bool:
    """Só difere no valor do campo obrigatório novo, desde que seja do tipo do campo."""
    novos = [m for m in mudancas if m.tipo == c.CAMPO_OBRIGATORIO_NOVO and m.lado == c.REQUISICAO]
    if not novos or not _regra_2(reparado, esperado, [m.caminho for m in novos]):
        return False
    for ch in reparado.chamadas:
        for m in novos:
            if (ch.http, ch.rota) != (m.metodo, m.rota) or ch.corpo is None:
                continue
            valores = _valores(ch.corpo, _partes(m.caminho))
            if not valores or not all(_do_tipo(v, m.depois) for v in valores):
                return False
    return True


# ---------------------------------------------------------------- troca de cenário

def _corpo_mudou_fora_da_diferenca(orig, rep, ch: _Chamada, mudancas: list[c.Mudanca]) -> bool:
    folhas_o, folhas_r = _folhas(orig), _folhas(rep)

    def _filtrar(folhas, so_na_origem: bool):
        saida = Counter()
        for (cam, val), n in folhas.items():
            if any(_debaixo(cam, m.caminho) for m in mudancas if m.tipo == c.REMOCAO) and so_na_origem:
                continue
            if any(cam == m.caminho for m in mudancas if m.tipo == c.ALTERACAO_TIPO):
                continue
            if not so_na_origem and any(_debaixo(cam, m.caminho) for m in mudancas
                                        if m.tipo == c.CAMPO_OBRIGATORIO_NOVO):
                continue
            if so_na_origem:
                for m in (m for m in mudancas if m.tipo == c.RENOMEACAO and _debaixo(cam, m.caminho)):
                    cam = m.novo_caminho + cam[len(m.caminho):]
            saida[(cam, val)] += n
        return saida

    return _filtrar(folhas_o, True) != _filtrar(folhas_r, False)


def _cenario_alterado(orig: _Metodo, rep: _Metodo, mudancas: list[c.Mudanca]) -> tuple[bool, str]:
    if orig.fora != rep.fora:
        return True, "o arquivo mudou fora do método afetado (fixture, outro teste ou anotação)"
    if len(orig.chamadas) != len(rep.chamadas):
        return True, "mudou o número de chamadas"
    for x, y in zip(orig.chamadas, rep.chamadas):
        if (x.http, x.url, x.status) != (y.http, y.url, y.status):
            return True, f"mudou a chamada {x.http} {x.url}"
        doa = [m for m in mudancas if (m.metodo, m.rota) == (x.http, x.rota)]
        req = [m for m in doa if m.lado == c.REQUISICAO]
        if (x.corpo is None) != (y.corpo is None):
            return True, "apareceu ou sumiu o corpo da requisição"
        if x.corpo is not None and _corpo_mudou_fora_da_diferenca(x.corpo, y.corpo, x, req):
            return True, "mudou o valor de um campo da requisição que a diferença de contrato não atinge"
        resp = [m for m in doa if m.lado == c.RESPOSTA] if x.status and 200 <= x.status < 300 else []

        def _livres(chamada, caminhos_de):
            return Counter(a for cam, a in chamada.assercoes
                           if not any(_debaixo(cam, p) for m in resp for p in caminhos_de(m)))

        if (_livres(x, lambda m: [m.caminho]) != _livres(y, lambda m: [m.caminho, m.novo_caminho or m.caminho])):
            return True, "mudou uma asserção sobre um campo que a diferença de contrato não atinge"
    return False, ""


# ---------------------------------------------------------------- API

def comparar(original: str, reparado: str, esperado: str | None, nome_metodo: str,
             mudancas: list[c.Mudanca], rotas: dict[str, set[str]]) -> Comparacao:
    """`esperado` é o arquivo depois da correção esperada; None numa regressão."""
    motivos = []
    try:
        o, r = _extrair(original, nome_metodo, rotas), _extrair(reparado, nome_metodo, rotas)
        cenario, motivo = _cenario_alterado(o, r, mudancas)
        if cenario:
            motivos.append(motivo)
    except tj.ErroDeAnalise as e:
        cenario = None
        motivos.append(f"cenário: a regra não decide ({e})")
    equivalente, regra = None, None
    if esperado is not None:
        try:
            e = _extrair(esperado, nome_metodo, rotas)
            if _sem_espacos(r.corpo) == _sem_espacos(e.corpo):
                regra = 1
            elif _regra_2(r, e):
                regra = 2
            elif _regra_3(r, e, mudancas):
                regra = 3
            equivalente = regra is not None
            if not equivalente:
                motivos.append("não equivalente pelas regras 1 a 3 da D95")
        except tj.ErroDeAnalise as exc:
            motivos.append(f"equivalência: a regra não decide ({exc})")
    return Comparacao(equivalente, cenario, tuple(motivos), regra)


# ---------------------------------------------------------------- revisão manual (D80, D109)

def revisao_manual(cmp: Comparacao, tem_esperado: bool, compilou: bool | None, passou: bool | None,
                   assercoes_enfraquecidas: bool | None) -> str | None:
    """Por que o reparo vai para a revisão manual da Barbara, ou None se a regra decide sozinha.

    - D80: a regra não decide a equivalência (havendo correção esperada) ou a troca de cenário;
    - D109: equivalente e com troca de cenário ao mesmo tempo (a correção esperada não troca o cenário);
    - D80: não equivalente, mas compila, passa e não enfraquece asserções.
    Numa regressão (D119) não há correção esperada: só a troca de cenário pode levar à revisão.
    """
    if cmp.cenario_alterado is None:
        return "D80: a regra não decide a troca de cenário"
    if tem_esperado and cmp.equivalente is None:
        return "D80: a regra não decide a equivalência"
    if cmp.equivalente is True and cmp.cenario_alterado is True:
        return "D109: equivalente e com troca de cenário ao mesmo tempo"
    if cmp.equivalente is False and compilou and passou and assercoes_enfraquecidas is False:
        return "D80: não equivalente, mas compila, passa e não enfraquece asserções"
    return None
