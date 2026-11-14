"""O agente único no runner (T49; D67, D74, D82, D87, D97), com Maven e LLM simulados. Nenhum teste chama a API paga."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agente_contrato import rodar as runner
from agente_contrato.registro_llm import LogDeChamadas
from tests.llm_simulado import FabricaSimulada, pede
from tests.test_registrar import VALIDACAO, carregar_validacao
from tests.test_rodar import REPARADO, Base, MavenFalso, legitima_reparada, rotulo


def unico_reparado() -> FabricaSimulada:
    """O agente único que vê a diferença, salva o reparo e entrega o rótulo, no mesmo laço."""
    return FabricaSimulada(pede("u1", "ver_diferenca"), pede("u2", "salvar_reparo", metodo_reparado=REPARADO),
                           rotulo("legitima"))


def por_tratamento(criadas: list | None = None):
    """A `criar_fabrica` da rodada: os agentes reparam com o FabricaDupla, o agente único com um laço só."""
    def criar(id_caso, repeticao, tratamento):
        if criadas is not None:
            criadas.append((id_caso, tratamento, repeticao))
        return unico_reparado() if tratamento == runner.AGENTE_UNICO else legitima_reparada()
    return criar


class BaseUnico(Base):
    def setUp(self):
        super().setUp()
        self.caso2 = runner.Caso("A1-002", self.caso.patch, "ProdutoTest", "busca")
        self.oraculo["A1-002"] = {"id_caso": "A1-002", "categoria": "renomeacao", "rotulo_oraculo": "legitima"}

    def rodada3(self, criar, sorteados=("A1-002",), repeticoes=1, **kw) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return runner.executar_rodada([self.caso, self.caso2], self.oraculo, self.api, "base", self.pasta,
                                          repeticoes, criar, ("p", "c"), MavenFalso(), aquecer_antes=False,
                                          tratamentos=runner.ORDEM_DOS_TRATAMENTOS,
                                          casos_agente_unico=set(sorteados), **kw)

    def log(self) -> dict:
        return json.loads((self.pasta / runner.ARQUIVO_LOG).read_text(encoding="utf-8"))


class TestRodadaComOAgenteUnico(BaseUnico):
    def test_ordem_d82_e_so_nos_sorteados(self):  # D82, D97
        criadas = []
        self.assertEqual(self.rodada3(por_tratamento(criadas), repeticoes=2), runner.SAIDA_OK)
        self.assertEqual([(r["id_caso"], r["tratamento"], r["repeticao"]) for r in self.resultados()],
                         [("A1-001", "baseline", 1), ("A1-001", "agentes", 1), ("A1-001", "agentes", 2),
                          ("A1-002", "baseline", 1), ("A1-002", "agentes", 1), ("A1-002", "agentes", 2),
                          ("A1-002", "agente_unico", 1), ("A1-002", "agente_unico", 2)])
        self.assertNotIn(("A1-001", "agente_unico", 1), criadas)

    def test_registro_no_formato_comum(self):  # D74, D87
        self.rodada3(por_tratamento())
        unico, = [r for r in self.resultados() if r["tratamento"] == "agente_unico"]
        self.assertEqual((unico["versao_agente"], unico["decisao"], unico["compilou"], unico["passou"], unico["erro"]),
                         ("agentica", "reparar", True, True, None))

    @unittest.skipUnless(VALIDACAO.exists(), "o repositório rest-test-healing-avaliacao não está ao lado deste")
    def test_o_validador_da_t20a_aceita(self):
        self.rodada3(por_tratamento())
        validacao = carregar_validacao()
        for r in self.resultados():
            if r["decisao"] == "reparar":  # D110: a revisão manual (T50) preenche os dois antes das métricas
                r = {**r, "equivalente_oraculo": True, "cenario_alterado": False}
            self.assertEqual(validacao.validar_registro(r), [], r["tratamento"])

    def test_log_e_pasta_da_execucao(self):  # T23h, T52
        self.rodada3(por_tratamento())
        entrada, = [x for x in self.log()["execucoes"] if x["tratamento"] == "agente_unico"]
        self.assertEqual((entrada["motivo"], entrada["rotulo"], entrada["chamadas"], entrada["incoerente"]),
                         ("reparo", "legitima", 3, False))
        pasta = self.pasta / "execucoes" / "A1-002-agente_unico-r1"
        caminho = json.loads((pasta / "caminho.json").read_text(encoding="utf-8"))
        self.assertEqual({v["etapa"] for v in caminho}, {"agente_unico"})
        self.assertIn("codigo", (pasta / "reparo.diff").read_text(encoding="utf-8"))
        self.assertTrue((self.pasta / "execucoes" / "A1-002-r1").exists())  # os agentes, com o nome de antes

    def test_custo_de_cada_tratamento_no_seu_registro(self):  # T49: a pendência da T53
        log = LogDeChamadas(self.pasta / runner.ARQUIVO_CHAMADAS)
        campos = dict.fromkeys(("modelo_retornado", "stop_reason", "thinking_tokens", "request_id", "latencia_s",
                                "commit_do_prompt", "resposta_bruta", "erro"))

        def criar(id_caso, repeticao, tratamento):
            etapa, custo = ("agente_unico", 0.003) if tratamento == runner.AGENTE_UNICO else ("classifier", 0.001)
            log.registrar(**campos, id_caso=id_caso, tratamento=tratamento, repeticao=repeticao, etapa=etapa,
                          input_tokens=100, output_tokens=10, custo_usd=custo)
            return por_tratamento()(id_caso, repeticao, tratamento)
        self.rodada3(criar)
        custo = {(r["id_caso"], r["tratamento"]): r["custo_usd"] for r in self.resultados()}
        self.assertEqual(custo, {("A1-001", "baseline"): 0.0, ("A1-001", "agentes"): 0.001,
                                 ("A1-002", "baseline"): 0.0, ("A1-002", "agentes"): 0.001,
                                 ("A1-002", "agente_unico"): 0.003})

    def test_sem_sorteio_roda_em_todos(self):  # só o ensaio do piloto (decisão E da T49)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner.executar_rodada([self.caso, self.caso2], self.oraculo, self.api, "base", self.pasta, 1,
                                   por_tratamento(), ("p", "c"), MavenFalso(), aquecer_antes=False,
                                   tratamentos=(runner.AGENTE_UNICO,))
        self.assertEqual([(r["id_caso"], r["tratamento"]) for r in self.resultados()],
                         [("A1-001", "agente_unico"), ("A1-002", "agente_unico")])


class TestRetomadaComOAgenteUnico(BaseUnico):
    SORTEIO = {"arquivo": "casos/sorteio-agente-unico.json", "commit": "s1", "semente": 4949, "ids": ["A1-002"]}

    def test_retomada_so_roda_o_agente_unico_que_faltou(self):  # T53 com o tratamento (T49)
        cab = runner.cabecalho("base", None, ("p", "c"), runner.LIMITE_CASO_S, self.SORTEIO)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):  # a sessão que caiu antes do agente único
            runner.executar_rodada([self.caso, self.caso2], self.oraculo, self.api, "base", self.pasta, 1,
                                   por_tratamento(), ("p", "c"), MavenFalso(), aquecer_antes=False,
                                   tratamentos=(runner.BASELINE, runner.TRATAMENTO), sorteio_do_log=self.SORTEIO)
        criadas = []
        anteriores = runner.carregar_anteriores(self.pasta, True, cab)
        self.assertEqual(self.rodada3(por_tratamento(criadas), anteriores=anteriores, sorteio_do_log=self.SORTEIO),
                         runner.SAIDA_OK)
        self.assertEqual(criadas, [("A1-002", "agente_unico", 1)])
        self.assertEqual(len(self.resultados()), 5)

    def test_outro_sorteio_e_recusado(self):  # D97: o sorteio não muda no meio da rodada
        self.rodada3(por_tratamento(), sorteio_do_log=self.SORTEIO)
        outro = {**self.SORTEIO, "ids": ["A1-001"]}
        with self.assertRaisesRegex(runner.RetomadaInvalida, "sorteio"):
            runner.carregar_anteriores(self.pasta, True, runner.cabecalho("base", None, ("p", "c"),
                                                                          runner.LIMITE_CASO_S, outro))

    def test_rodada_sem_o_agente_unico_tem_o_cabecalho_de_antes(self):  # as pastas da T47, T51 e T53 continuam
        self.assertNotIn("sorteio", runner.cabecalho("base", None, ("p", "c"), runner.LIMITE_CASO_S))


class TestSorteioDoLog(unittest.TestCase):
    """O runner só aceita o sorteio gravado e do mesmo oráculo da rodada (D97)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        from tests.test_preparar_copia import git
        git("init", "-q", cwd=self.raiz)
        git("config", "user.email", "t@t", cwd=self.raiz)
        git("config", "user.name", "t", cwd=self.raiz)
        (self.raiz / "casos").mkdir()
        self.git = lambda *a: git(*a, cwd=self.raiz)
        self.oraculo = {"casos": [{"id_caso": "A1-013"}, {"id_caso": "A1-020"}]}
        self.do_oraculo = {"arquivo": "casos/oraculo-agente1-final.json", "commit": "o1"}

    def gravar(self, dados: dict, commit: bool = True) -> Path:
        arquivo = self.raiz / "casos" / "sorteio-agente-unico.json"
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
        if commit:
            self.git("add", ".")
            self.git("commit", "-q", "-m", "sorteio")
        return arquivo

    def dados(self, oraculo="casos/oraculo-agente1-final.json", ids=("A1-020",)):
        return {"semente": 4949, "oraculo": {"arquivo": oraculo}, "sorteados": [{"id_caso": i} for i in ids]}

    def test_sorteio_gravado_e_do_mesmo_oraculo(self):
        r = runner.sorteio_do_log(self.gravar(self.dados()), self.do_oraculo, self.oraculo, self.raiz)
        self.assertEqual((r["arquivo"], r["semente"], r["ids"]), ("casos/sorteio-agente-unico.json", 4949, ["A1-020"]))
        self.assertEqual(len(r["commit"]), 40)

    def test_sorteio_com_mudanca_nao_gravada(self):
        arquivo = self.gravar(self.dados())
        self.gravar(self.dados(ids=("A1-013",)), commit=False)
        with self.assertRaisesRegex(runner.SorteioInvalido, "não gravada"):
            runner.sorteio_do_log(arquivo, self.do_oraculo, self.oraculo, self.raiz)

    def test_sorteio_de_outro_oraculo(self):  # ex.: a rodada com o oráculo do piloto
        arquivo = self.gravar(self.dados())
        with self.assertRaisesRegex(runner.SorteioInvalido, "do oráculo"):
            runner.sorteio_do_log(arquivo, {"arquivo": "casos/oraculo-agente1.json"}, self.oraculo, self.raiz)

    def test_caso_sorteado_fora_do_oraculo(self):
        arquivo = self.gravar(self.dados(ids=("A1-099",)))
        with self.assertRaisesRegex(runner.SorteioInvalido, "A1-099"):
            runner.sorteio_do_log(arquivo, self.do_oraculo, self.oraculo, self.raiz)


class TestMainComOAgenteUnico(BaseUnico):
    def test_com_o_oraculo_do_piloto_o_agente_unico_nao_roda_e_nada_e_lido(self):  # D97
        erro = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(erro):
            codigo = runner.main(["--api", str(self.api), "--saida", str(self.pasta), "--orcamento-usd", "0.1",
                                  "--tratamentos", "agente_unico"], sdk=None)
        self.assertEqual(codigo, runner.SAIDA_NAO_CONGELADO)
        self.assertIn("do oráculo casos/oraculo-agente1-final.json", erro.getvalue())
        self.assertFalse(self.pasta.exists())

    def test_o_sorteio_versionado_e_o_da_t49(self):  # D97: gravado antes de qualquer execução
        do_oraculo = runner.oraculo_do_log(runner.RAIZ_REPO / "casos" / "oraculo-agente1-final.json")
        oraculo = json.loads((runner.RAIZ_REPO / do_oraculo["arquivo"]).read_text(encoding="utf-8"))
        r = runner.sorteio_do_log(runner.sorteio.ARQUIVO_SORTEIO, do_oraculo, oraculo)
        self.assertEqual((r["semente"], r["ids"]), (4949, ["A1-015", "A1-018", "A1-019", "A1-024", "A1-026",
                                                          "A1-029", "A1-031", "A1-035"]))


if __name__ == "__main__":
    unittest.main()
