"""Registro de resultados no formato da D74 (Planejamento do Estudo, acordo de avaliação comum)."""

import json
import os
import tempfile
from pathlib import Path

CAMPOS = ("id_caso", "agente", "tratamento", "versao_agente", "categoria", "rotulo_oraculo",
          "decisao", "compilou", "passou", "equivalente_oraculo", "assercoes_enfraquecidas",
          "cenario_alterado", "repeticao", "tempo_s", "tokens", "custo_usd", "erro")

_VALORES = {
    "agente": {"agente1", "agente2"},
    "tratamento": {"baseline", "agentes", "agente_unico"},
    "versao_agente": {None, "v1", "agentica"},
    "rotulo_oraculo": {"legitima", "problema_real"},
    "decisao": {"reparar", "nao_reparar"},
    "erro": {None, "limite_chamadas", "max_tokens", "guarda", "timeout", "erro_llm",
             "saida_invalida", "erro_execucao"},
}
_NULOS_SE_NAO_REPARAR = ("compilou", "equivalente_oraculo", "assercoes_enfraquecidas", "cenario_alterado")
_BOOLEANOS = ("compilou", "passou", "equivalente_oraculo", "assercoes_enfraquecidas", "cenario_alterado")


def chave(registro: dict) -> tuple:
    return tuple(registro[k] for k in ("id_caso", "agente", "tratamento", "versao_agente", "repeticao"))


def problemas(registro: dict) -> list[str]:
    """Lista o que o registro tem de errado; vazia se ele está de acordo com a D74."""
    lista = [f"campo ausente: {c}" for c in CAMPOS if c not in registro]
    lista += [f"campo desconhecido: {c}" for c in registro if c not in CAMPOS]
    if lista:
        return lista
    for campo, validos in _VALORES.items():
        if registro[campo] not in validos:
            lista.append(f"{campo}: valor fora dos permitidos ({registro[campo]!r})")
    for campo in _BOOLEANOS:
        if registro[campo] is not None and not isinstance(registro[campo], bool):
            lista.append(f"{campo}: esperado booleano ou nulo")
    if not isinstance(registro["passou"], bool):
        lista.append("passou: esperado booleano")
    if not (isinstance(registro["repeticao"], int) and registro["repeticao"] >= 1):
        lista.append("repeticao: esperado inteiro >= 1")
    if registro["decisao"] == "nao_reparar":
        lista += [f"{c}: deve ser nulo quando a decisão é nao_reparar"
                  for c in _NULOS_SE_NAO_REPARAR if registro[c] is not None]
    elif registro["compilou"] is None:
        lista.append("compilou: nulo só quando a decisão é nao_reparar")
    return lista


def gravar(caminho: Path, versao_api: str, execucoes: list[dict]) -> None:
    """Valida e regrava o arquivo inteiro por um arquivo temporário, para uma interrupção
    não corromper os registros já gravados."""
    erros = [f"{r.get('id_caso')}: {p}" for r in execucoes for p in problemas(r)]
    if erros:
        raise ValueError("; ".join(erros))
    chaves = [chave(r) for r in execucoes]
    if len(set(chaves)) != len(chaves):
        raise ValueError("chave (id_caso, agente, tratamento, versao_agente, repeticao) repetida")
    conteudo = {"versao_api": versao_api,
                "execucoes": [{c: r[c] for c in CAMPOS} for r in execucoes]}
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=caminho.parent,
                                     prefix=caminho.name, suffix=".tmp", delete=False) as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, caminho)
