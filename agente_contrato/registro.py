"""Registro de resultados da versão agêntica do Agente 1 (T23h): o fim de cada caso no formato comum (D74).

Tudo aqui é código determinístico: o LLM já terminou. Este módulo só traduz o que aconteceu no laço
para `decisao` e `erro`, monta o registro e grava o log de cada execução.
"""
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agente_contrato.agentes import ResultadoAgente, ResultadoRepair
from agente_contrato.ferramentas import RECUSA_DO_GUARDA
from agente_contrato.laco import RespostaModelo

REPARAR = "reparar"
NAO_REPARAR = "nao_reparar"


@dataclass(frozen=True)
class Fim:
    """Como o caso terminou, nos termos da D74."""
    decisao: str     # "reparar" ou "nao_reparar"
    erro: str | None  # um dos códigos da D74, ou None


def respostas_do_salvar(repair: ResultadoRepair | None) -> list:
    """As respostas que o código deu a cada pedido de salvar_reparo do Repair, em ordem."""
    if repair is None:
        return []
    historico = repair.laco.historico
    pedidos = {p.id for item in historico if isinstance(item, RespostaModelo)
               for p in item.pedidos if p.nome == "salvar_reparo"}
    return [r for item in historico if isinstance(item, tuple) for r in item if r.id_pedido in pedidos]


def traduzir(agente: ResultadoAgente) -> Fim:
    """Traduz o motivo de fim da T23f para `decisao` e `erro` (D74, D102, D111d, D118, D129, D130)."""
    respostas = respostas_do_salvar(agente.repair)
    aceito = any(not r.erro for r in respostas)
    recusado = any(r.erro and r.conteudo.startswith(RECUSA_DO_GUARDA) for r in respostas)
    motivo = agente.motivo
    if motivo == "limite_do_caso":  # D111d; o timeout vence o guarda (D130)
        return Fim(REPARAR if aceito else NAO_REPARAR, "timeout")  # reparo salvo: como a D118 (D130)
    if motivo == "reparo":  # um reparo aceito vence uma recusa anterior (D130)
        return Fim(REPARAR, None)
    if motivo == "nao_reparar":  # rótulo problema_real: o Repair não rodou, e isso não é erro
        return Fim(NAO_REPARAR, None)
    if motivo == "saida_invalida":  # D102, D117c
        return Fim(NAO_REPARAR, "saida_invalida")
    if motivo == "classifier_limite_de_chamadas":
        return Fim(NAO_REPARAR, "limite_chamadas")
    if motivo in ("repair_limite_de_chamadas", "repair_sem_reparo") and recusado:
        return Fim(NAO_REPARAR, "guarda")  # D129: pelo menos uma recusa e nenhum reparo aceito
    if motivo == "repair_limite_de_chamadas":
        return Fim(NAO_REPARAR, "limite_chamadas")
    if motivo == "repair_sem_reparo":  # D130: como o metodo_reparado que não se encaixa na D102
        return Fim(NAO_REPARAR, "saida_invalida")
    raise ValueError(f"motivo de fim desconhecido: {motivo}")


CAMPOS = ("id_caso", "agente", "tratamento", "versao_agente", "categoria", "rotulo_oraculo",
          "decisao", "compilou", "passou", "equivalente_oraculo", "assercoes_enfraquecidas",
          "cenario_alterado", "repeticao", "tempo_s", "tokens", "custo_usd", "erro")  # D74, nesta ordem


def registrar(fim: Fim, oraculo_do_caso: dict, repeticao: int, compilou: bool | None, passou: bool,
              tempo_s: float, tokens: int = 0, custo_usd: float = 0.0,
              equivalente_oraculo: bool | None = None, cenario_alterado: bool | None = None) -> dict:
    """O registro da D74 de uma execução. Chamada só depois do caso: é o único lugar que lê o oráculo.

    `compilou` e `passou` vêm do Maven final (T23j); `equivalente_oraculo` e `cenario_alterado`, do
    comparador (T50), e ficam nulos até lá: num caso legítimo reparado, o validador da T20a recusa o
    arquivo até a revisão manual preencher o veredito (D110). `tokens` e `custo_usd` vêm da T23i.
    """
    registro = {"id_caso": oraculo_do_caso["id_caso"], "agente": "agente1", "tratamento": "agentes",
                "versao_agente": "agentica", "categoria": oraculo_do_caso["categoria"],
                "rotulo_oraculo": oraculo_do_caso["rotulo_oraculo"], "decisao": fim.decisao,
                "compilou": None, "passou": False, "equivalente_oraculo": None,
                "assercoes_enfraquecidas": None, "cenario_alterado": None, "repeticao": repeticao,
                "tempo_s": round(tempo_s, 4), "tokens": tokens, "custo_usd": custo_usd, "erro": fim.erro}
    if fim.decisao == NAO_REPARAR:  # o arquivo não mudou: o teste continua falhando (D102)
        return registro
    if fim.erro == "timeout":  # reparo salvo sem conferência a tempo (D118, D130)
        compilou, passou = False, False
    registro.update(compilou=compilou, passou=passou, equivalente_oraculo=equivalente_oraculo,
                    assercoes_enfraquecidas=False,  # o guarda aceitou o reparo (D129)
                    cenario_alterado=cenario_alterado)
    return registro


def gravar_resultados(caminho: Path, versao_api: str, registros: list[dict]) -> None:
    """Regrava o arquivo de resultados inteiro por um temporário, como na v1: uma queda no meio da
    gravação não corrompe os registros já gravados."""
    chaves = [tuple(r[c] for c in ("id_caso", "repeticao")) for r in registros]
    if len(set(chaves)) != len(chaves):
        raise ValueError("execução (id_caso, repeticao) repetida")
    conteudo = {"versao_api": versao_api, "execucoes": [{c: r[c] for c in CAMPOS} for r in registros]}
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=caminho.parent, prefix=caminho.name,
                                     suffix=".tmp", delete=False) as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, caminho)


def recusas_do_guarda(agente: ResultadoAgente) -> list[str]:
    """As mensagens de cada recusa do guarda no salvar_reparo, em ordem (D129)."""
    return [r.conteudo for r in respostas_do_salvar(agente.repair)
            if r.erro and r.conteudo.startswith(RECUSA_DO_GUARDA)]


def entrada_do_log(id_caso: str, repeticao: int, agente: ResultadoAgente, fim: Fim,
                   commit_do_prompt: str, commit_do_codigo: str) -> dict:
    """O que explica o registro (o porquê), para a análise e a revisão manual; as métricas não usam.

    Não traz nada do oráculo. `commit_do_prompt` e `commit_do_codigo` vêm de `prompts.commit_dos_prompts`
    (D105): com `+alterado`, a execução não diz com que prompt ou código rodou.
    """
    classifier, repair = agente.classifier, agente.repair
    return {"id_caso": id_caso, "repeticao": repeticao, "motivo": agente.motivo,
            "decisao": fim.decisao, "erro": fim.erro,
            "rotulo_classifier": classifier.rotulo, "justificativa": classifier.justificativa,
            "detalhe": classifier.detalhe,  # por que a saída do Classifier foi inválida
            "chamadas_classifier": classifier.laco.chamadas,
            "chamadas_repair": repair.laco.chamadas if repair else 0,
            "recusas_do_guarda": recusas_do_guarda(agente),
            "commit_do_prompt": commit_do_prompt, "commit_do_codigo": commit_do_codigo}


def caminho_do_agente(agente: ResultadoAgente) -> list[dict]:
    """O caminho do agente: as ferramentas pedidas em cada volta do laço, com o resultado de cada uma.

    Uma volta é uma resposta do modelo; na última, ele termina sem pedir ferramenta (`terminou`). Quem
    escolheu as ferramentas foi o LLM; este código só lê o histórico. Serve ao relatório visual (T52).
    """
    caminho = []
    lacos = [("classifier", agente.classifier.laco)] + ([("repair", agente.repair.laco)] if agente.repair else [])
    for etapa, laco in lacos:
        respostas = [item for item in laco.historico if isinstance(item, RespostaModelo)]
        resultados = {r.id_pedido: r for item in laco.historico if isinstance(item, tuple) for r in item}
        for volta, resposta in enumerate(respostas, start=1):
            caminho.append({"etapa": etapa, "volta": volta, "terminou": resposta.terminou,
                            "ferramentas": [{"nome": p.nome, "erro": resultados[p.id].erro}
                                            for p in resposta.pedidos]})
    return caminho

