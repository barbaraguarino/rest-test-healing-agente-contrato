import unittest

from agente_contrato.agentes import rodar_agente
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.registro import caminho_do_agente
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaDupla, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso
from tests.test_traduzir import FALHA, LEGITIMA, PROBLEMA, salva

ANTES = '@Test\nvoid lista() {\n    get("/produtos").andExpect(jsonPath("$.nome").exists());\n}\n'


def rodar(ferramentas, roteiro_classifier, roteiro_repair=()):
    fabrica = FabricaDupla(list(roteiro_classifier), list(roteiro_repair))
    return rodar_agente(fabrica, ferramentas.dicionario(), RelogioCaso(agora=RelogioFalso()),
                        "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", FALHA, ANTES)


class TestCaminhoDoAgente(unittest.TestCase):
    def test_ferramentas_de_cada_volta_nas_duas_etapas(self):
        ferramentas = FerramentasFalsas(ler_arquivo=ErroDeFerramenta("Leitura não permitida: pom.xml."))
        agente = rodar(ferramentas, [pede("c1", "ver_diferenca"), pede("c2", "ler_arquivo", caminho="pom.xml"),
                                     LEGITIMA],
                       [salva("r1"), pede("r2", "rodar_teste"), RespostaModelo("feito")])
        self.assertEqual(caminho_do_agente(agente), [
            {"etapa": "classifier", "volta": 1, "terminou": False,
             "ferramentas": [{"nome": "ver_diferenca", "erro": False}]},
            {"etapa": "classifier", "volta": 2, "terminou": False,
             "ferramentas": [{"nome": "ler_arquivo", "erro": True}]},
            {"etapa": "classifier", "volta": 3, "terminou": True, "ferramentas": []},
            {"etapa": "repair", "volta": 1, "terminou": False,
             "ferramentas": [{"nome": "salvar_reparo", "erro": False}]},
            {"etapa": "repair", "volta": 2, "terminou": False,
             "ferramentas": [{"nome": "rodar_teste", "erro": False}]},
            {"etapa": "repair", "volta": 3, "terminou": True, "ferramentas": []},
        ])

    def test_sem_repair_so_o_classifier(self):
        agente = rodar(FerramentasFalsas(), [PROBLEMA])
        self.assertEqual(caminho_do_agente(agente),
                         [{"etapa": "classifier", "volta": 1, "terminou": True, "ferramentas": []}])

