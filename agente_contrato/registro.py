"""Registro de resultados da versão agêntica do Agente 1 (T23h): o fim de cada caso no formato comum (D74).

Tudo aqui é código determinístico: o LLM já terminou. Este módulo só traduz o que aconteceu no laço
para `decisao` e `erro`, monta o registro e grava o log de cada execução.
"""
from dataclasses import dataclass

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
