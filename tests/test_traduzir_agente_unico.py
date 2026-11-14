"""Tradução do fim do agente único para o formato comum (T49; D74, D102, D111d, D129, D130, D132). LLM simulado."""
import unittest

from agente_contrato.agentes import rodar_agente_unico
from agente_contrato.ferramentas import RECUSA_DO_GUARDA
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.registro import Fim, caminho_do_agente, entrada_do_log_agente_unico, traduzir_agente_unico
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaSimulada, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso

LEGITIMA = RespostaModelo('{"rotulo": "legitima", "justificativa": "O campo nome virou titulo."}')
PROBLEMA = RespostaModelo('{"rotulo": "problema_real", "justificativa": "O código não segue o contrato."}')
RECUSA = ErroDeFerramenta(f"{RECUSA_DO_GUARDA} (menos asserções). O arquivo continua como estava.")


def salva(id_pedido: str) -> RespostaModelo:
    return pede(id_pedido, "salvar_reparo", metodo_reparado="void lista() {}")


def em_sequencia(*respostas):
    """Uma ferramenta que responde, a cada chamada, a próxima da lista (texto ou exceção)."""
    fila = list(respostas)

    def responder():
        r = fila.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return responder


class TestTraduzirAgenteUnico(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas()
        self.tempo = RelogioFalso()
        self.relogio = RelogioCaso(agora=self.tempo)

    def agente(self, *roteiro):
        return rodar_agente_unico(FabricaSimulada(*roteiro), self.ferramentas.dicionario(), self.relogio,
                                  "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", None,
                                  "@Test\nvoid lista() {}")

    def fim(self, *roteiro) -> Fim:
        return traduzir_agente_unico(self.agente(*roteiro))

    def test_reparo(self):
        self.assertEqual(self.fim(salva("s1"), LEGITIMA), Fim("reparar", None))

    def test_reparo_e_depois_o_limite(self):
        self.assertEqual(self.fim(salva("s1"), *[pede(f"t{i}", "rodar_teste") for i in range(10)]),
                         Fim("reparar", None))

    def test_problema_real_sem_reparo_nao_e_erro(self):
        self.assertEqual(self.fim(PROBLEMA), Fim("nao_reparar", None))

    def test_problema_real_com_reparo_vale_o_arquivo(self):
        self.assertEqual(self.fim(salva("s1"), PROBLEMA), Fim("reparar", None))

    def test_limite_sem_reparo(self):  # D130
        self.assertEqual(self.fim(*[pede(f"c{i}", "ler_arquivo", caminho="src") for i in range(10)]),
                         Fim("nao_reparar", "limite_chamadas"))

    def test_legitima_sem_reparo(self):  # D130
        self.assertEqual(self.fim(LEGITIMA), Fim("nao_reparar", "saida_invalida"))

    def test_saida_invalida_sem_reparo(self):  # D102
        self.assertEqual(self.fim(RespostaModelo("É legítima.")), Fim("nao_reparar", "saida_invalida"))

    def test_saida_invalida_com_reparo(self):  # como a D132
        self.assertEqual(self.fim(salva("s1"), RespostaModelo("Reparei.")), Fim("reparar", "saida_invalida"))

    def test_recusa_sem_reparo_aceito_e_guarda(self):  # D129, nos três fins sem reparo
        self.ferramentas.respostas["salvar_reparo"] = RECUSA
        for roteiro in ([salva("s1"), LEGITIMA], [salva("s1"), RespostaModelo("Não deu.")],
                        [salva("s1")] + [pede(f"c{i}", "rodar_teste") for i in range(9)],
                        [salva("s1"), PROBLEMA]):
            with self.subTest(fim=roteiro[-1].texto):
                self.assertEqual(self.fim(*roteiro), Fim("nao_reparar", "guarda"))

    def test_reparo_aceito_vence_a_recusa_anterior(self):  # D130
        self.ferramentas.respostas["salvar_reparo"] = em_sequencia(RECUSA, "Reparo salvo.")
        self.assertEqual(self.fim(salva("s1"), salva("s2"), LEGITIMA), Fim("reparar", None))

    def test_tempo_esgotado_vence_o_guarda(self):  # D111d, D130
        def recusa_e_gasta_o_tempo():
            self.tempo.andar(200)
            raise RECUSA
        self.ferramentas.respostas["salvar_reparo"] = recusa_e_gasta_o_tempo
        self.assertEqual(self.fim(salva("s1"), LEGITIMA), Fim("nao_reparar", "timeout"))

    def test_tempo_esgotado_com_reparo_salvo(self):  # como a D118
        def salva_e_gasta_o_tempo():
            self.tempo.andar(200)
            return "Reparo salvo."
        self.ferramentas.respostas["salvar_reparo"] = salva_e_gasta_o_tempo
        self.assertEqual(self.fim(salva("s1"), LEGITIMA), Fim("reparar", "timeout"))


class TestLogDoAgenteUnico(unittest.TestCase):
    def setUp(self):
        self.ferramentas = FerramentasFalsas()
        self.relogio = RelogioCaso(agora=RelogioFalso())

    def agente(self, *roteiro):
        return rodar_agente_unico(FabricaSimulada(*roteiro), self.ferramentas.dicionario(), self.relogio,
                                  "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", None,
                                  "@Test\nvoid lista() {}")

    def test_entrada_do_log(self):
        self.ferramentas.respostas["salvar_reparo"] = em_sequencia(RECUSA, "Reparo salvo.")
        agente = self.agente(pede("c1", "ver_diferenca"), salva("s1"), salva("s2"), PROBLEMA)
        entrada = entrada_do_log_agente_unico("A1-015", 2, agente, traduzir_agente_unico(agente), "p", "c")
        self.assertEqual({k: entrada[k] for k in ("motivo", "decisao", "erro", "rotulo", "incoerente", "chamadas")},
                         {"motivo": "reparo", "decisao": "reparar", "erro": None, "rotulo": "problema_real",
                          "incoerente": True, "chamadas": 4})
        self.assertEqual(len(entrada["recusas_do_guarda"]), 1)
        self.assertEqual((entrada["commit_do_prompt"], entrada["commit_do_codigo"]), ("p", "c"))

    def test_caminho_e_um_laco_so(self):  # para a T52
        agente = self.agente(pede("c1", "ver_diferenca"), salva("s1"), LEGITIMA)
        caminho = caminho_do_agente(agente)
        self.assertEqual([(v["etapa"], v["volta"], v["terminou"]) for v in caminho],
                         [("agente_unico", 1, False), ("agente_unico", 2, False), ("agente_unico", 3, True)])
        self.assertEqual(caminho[1]["ferramentas"], [{"nome": "salvar_reparo", "erro": False}])


if __name__ == "__main__":
    unittest.main()
