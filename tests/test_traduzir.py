import unittest

from agente_contrato.agentes import rodar_agente
from agente_contrato.execucao import Falha
from agente_contrato.ferramentas import RECUSA_DO_GUARDA
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.registro import Fim, traduzir
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaDupla, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

LEGITIMA = RespostaModelo('{"rotulo": "legitima", "justificativa": "O campo nome virou titulo."}')
PROBLEMA = RespostaModelo('{"rotulo": "problema_real", "justificativa": "O código não segue o contrato."}')
FALHA = Falha("failure", "java.lang.AssertionError", "No value at JSON path \"$.nome\"")
RECUSA = ErroDeFerramenta(f"{RECUSA_DO_GUARDA} (menos asserções). O arquivo continua como estava.")


def salva(id_pedido: str) -> RespostaModelo:
    return pede(id_pedido, "salvar_reparo", metodo_reparado="void lista() {}")


class TestTraduzir(unittest.TestCase):
    """Um teste por motivo de fim da T23f, rodando o agente inteiro com o LLM simulado."""

    def setUp(self):
        self.ferramentas = FerramentasFalsas()
        self.tempo = RelogioFalso()
        self.relogio = RelogioCaso(agora=self.tempo)

    def fim(self, roteiro_classifier, roteiro_repair=()) -> Fim:
        fabrica = FabricaDupla(list(roteiro_classifier), list(roteiro_repair))
        agente = rodar_agente(fabrica, self.ferramentas.dicionario(), self.relogio,
                              "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", FALHA,
                              "@Test\nvoid lista() {}")
        return traduzir(agente)

    def test_reparo(self):
        self.assertEqual(self.fim([LEGITIMA], [salva("r1"), RespostaModelo("feito")]), Fim("reparar", None))

    def test_problema_real_nao_e_erro(self):
        self.assertEqual(self.fim([PROBLEMA]), Fim("nao_reparar", None))

    def test_saida_invalida_do_classifier(self):  # D102
        self.assertEqual(self.fim([RespostaModelo("não sei")]), Fim("nao_reparar", "saida_invalida"))

    def test_limite_de_chamadas_do_classifier(self):  # D62, D74
        roteiro = [pede(f"c{i}", "ler_arquivo", caminho="src") for i in range(5)]
        self.assertEqual(self.fim(roteiro), Fim("nao_reparar", "limite_chamadas"))

    def test_limite_de_chamadas_do_repair(self):
        roteiro = [pede(f"r{i}", "ler_arquivo", caminho="src") for i in range(7)]
        self.assertEqual(self.fim([LEGITIMA], roteiro), Fim("nao_reparar", "limite_chamadas"))

    def test_repair_sem_reparo_e_sem_recusa_e_saida_invalida(self):  # D130
        self.assertEqual(self.fim([LEGITIMA], [RespostaModelo("Não sei reparar.")]),
                         Fim("nao_reparar", "saida_invalida"))

    def test_metodo_nao_encontrado_no_salvar_e_saida_invalida(self):  # D130, como na D102
        self.ferramentas.respostas["salvar_reparo"] = ErroDeFerramenta("O reparo não foi salvo: método não achado.")
        self.assertEqual(self.fim([LEGITIMA], [salva("r1"), RespostaModelo("Desisto.")]),
                         Fim("nao_reparar", "saida_invalida"))

    def test_recusa_do_guarda_e_o_repair_termina(self):  # D129
        self.ferramentas.respostas["salvar_reparo"] = RECUSA
        self.assertEqual(self.fim([LEGITIMA], [salva("r1"), RespostaModelo("Desisto.")]),
                         Fim("nao_reparar", "guarda"))

    def test_recusa_do_guarda_e_o_limite_de_chamadas(self):  # D129: o guarda vence o limite
        self.ferramentas.respostas["salvar_reparo"] = RECUSA
        self.assertEqual(self.fim([LEGITIMA], [salva(f"r{i}") for i in range(7)]), Fim("nao_reparar", "guarda"))

    def test_recusa_e_depois_reparo_aceito_e_reparo(self):  # D130
        tentativas = []

        def salvar():
            tentativas.append(1)
            if len(tentativas) == 1:
                raise RECUSA
            return "Reparo salvo."
        self.ferramentas.respostas["salvar_reparo"] = salvar
        self.assertEqual(self.fim([LEGITIMA], [salva("r1"), salva("r2"), RespostaModelo("feito")]),
                         Fim("reparar", None))

    def test_tempo_do_caso_no_classifier_e_timeout(self):  # D111d
        self.ferramentas.respostas["rodar_teste"] = lambda: self.tempo.andar(200) or "O teste falhou."
        self.assertEqual(self.fim([pede("c1", "rodar_teste"), LEGITIMA]), Fim("nao_reparar", "timeout"))

    def test_tempo_do_caso_depois_de_reparo_salvo_e_timeout_com_reparo(self):  # D118, D130
        self.ferramentas.respostas["rodar_teste"] = lambda: self.tempo.andar(200) or "O teste falhou."
        roteiro = [salva("r1"), pede("r2", "rodar_teste"), RespostaModelo("feito")]
        self.assertEqual(self.fim([LEGITIMA], roteiro), Fim("reparar", "timeout"))

    def test_timeout_vence_a_recusa_do_guarda(self):  # D130
        self.ferramentas.respostas["salvar_reparo"] = RECUSA
        self.ferramentas.respostas["rodar_teste"] = lambda: self.tempo.andar(200) or "O teste falhou."
        roteiro = [salva("r1"), pede("r2", "rodar_teste"), RespostaModelo("feito")]
        self.assertEqual(self.fim([LEGITIMA], roteiro), Fim("nao_reparar", "timeout"))
