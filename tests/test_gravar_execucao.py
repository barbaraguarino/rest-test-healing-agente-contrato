import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.agentes import rodar_agente
from agente_contrato.laco import ErroDeFerramenta, RespostaModelo
from agente_contrato.registro import caminho_do_agente, gravar_execucao
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FabricaDupla, FerramentasFalsas, pede
from tests.relogio_falso import RelogioFalso
from tests.test_traduzir import FALHA, LEGITIMA, PROBLEMA, salva

ANTES = '@Test\nvoid lista() {\n    get("/produtos").andExpect(jsonPath("$.nome").exists());\n}\n'
DEPOIS = '@Test\nvoid lista() {\n    get("/produtos").andExpect(jsonPath("$.titulo").exists());\n}\n'


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


class TestGravarExecucao(unittest.TestCase):
    def gravar(self, depois):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pasta = Path(tmp.name) / "A1-001-r1"
        caminho = [{"etapa": "classifier", "volta": 1, "terminou": True, "ferramentas": []}]
        gravar_execucao(pasta, {"id_caso": "A1-001", "commit_do_prompt": "abc123"}, caminho, ANTES, depois)
        return pasta

    def test_grava_os_cinco_arquivos(self):
        pasta = self.gravar(DEPOIS)
        self.assertEqual(sorted(a.name for a in pasta.iterdir()),
                         ["antes.java", "caminho.json", "depois.java", "log.json", "reparo.diff"])
        self.assertEqual((pasta / "antes.java").read_text(encoding="utf-8"), ANTES)
        self.assertEqual((pasta / "depois.java").read_text(encoding="utf-8"), DEPOIS)
        self.assertEqual(json.loads((pasta / "log.json").read_text(encoding="utf-8"))["commit_do_prompt"], "abc123")
        self.assertEqual(json.loads((pasta / "caminho.json").read_text(encoding="utf-8"))[0]["etapa"], "classifier")

    def test_diff_mostra_a_linha_trocada(self):
        diff = (self.gravar(DEPOIS) / "reparo.diff").read_text(encoding="utf-8")
        self.assertTrue(diff.startswith("--- antes.java\n+++ depois.java\n"))
        self.assertIn('-    get("/produtos").andExpect(jsonPath("$.nome").exists());\n', diff)
        self.assertIn('+    get("/produtos").andExpect(jsonPath("$.titulo").exists());\n', diff)

    def test_sem_reparo_o_diff_fica_vazio(self):
        self.assertEqual((self.gravar(ANTES) / "reparo.diff").read_text(encoding="utf-8"), "")
