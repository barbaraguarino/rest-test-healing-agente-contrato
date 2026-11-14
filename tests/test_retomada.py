"""Escolha do oráculo e retomada de rodada interrompida (T53), com Maven e LLM simulados: nenhum teste
chama a API paga, e os testes do `main` conferem que a chave nem é lida quando a pasta é recusada.

As letras nos nomes das classes são as do pedido da T53:
a. pula o que já está gravado nos resultados e no log;
b. refaz do início a execução que parou no meio, e as chamadas pagas dela ficam "sem registro";
c. o --orcamento-usd vale para a rodada inteira;
d. recusa, sem ler a chave, se mudou o oráculo, a tag, os prompts, o código ou os limites;
e. sem --retomar, uma pasta com rodada anterior é recusada.
"""
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from agente_contrato import rodar as runner
from agente_contrato.registro_llm import LogDeChamadas, gasto_do_log
from tests.test_rodar import Base, MavenFalso, legitima_reparada

ORACULO = {"arquivo": "casos/oraculo.json", "commit": "o1"}
COMMITS = ("p", "c")


class Interrompido(KeyboardInterrupt):
    """Faz o papel do Ctrl+C ou da queda no meio de uma execução: nada no runner o trata."""


def chamada(pasta: Path, id_caso: str, repeticao: int, custo: float = 0.001, tratamento: str = "agentes") -> None:
    """Uma linha paga no chamadas.jsonl, como a que o ModeloClaude grava antes de qualquer coisa (D106)."""
    campos = dict.fromkeys(("modelo_retornado", "stop_reason", "thinking_tokens", "request_id", "latencia_s",
                            "commit_do_prompt", "resposta_bruta", "erro"))
    LogDeChamadas(pasta / runner.ARQUIVO_CHAMADAS).registrar(
        **campos, id_caso=id_caso, tratamento=tratamento, repeticao=repeticao,
        etapa="classifier" if tratamento == "agentes" else "agente_unico", input_tokens=500, output_tokens=100,
        custo_usd=custo)


class ModeloQueCai:
    """O Classifier que grava duas chamadas pagas e cai antes de responder."""

    def __init__(self, pasta: Path, id_caso: str, repeticao: int):
        self.pasta, self.id_caso, self.repeticao = pasta, id_caso, repeticao

    def __call__(self, sistema, definicoes, formato=None):
        def modelo(historico):
            chamada(self.pasta, self.id_caso, self.repeticao)
            chamada(self.pasta, self.id_caso, self.repeticao)
            raise Interrompido()
        return modelo


class BaseRetomada(Base):
    def setUp(self):
        super().setUp()
        self.casos = [runner.Caso(f"A1-00{n}", self.caso.patch, "ProdutoTest", "busca") for n in (1, 2)]
        self.oraculo.update({c.id_caso: {**self.oraculo["A1-001"], "id_caso": c.id_caso} for c in self.casos})
        self.criadas = []  # (id_caso, repeticao) de cada fábrica criada, em ordem: as execuções que rodaram

    def fabrica(self, cair_em: tuple[str, int] | None = None):
        def criar(id_caso, repeticao):
            self.criadas.append((id_caso, repeticao))
            if (id_caso, repeticao) == cair_em:
                return ModeloQueCai(self.pasta, id_caso, repeticao)
            chamada(self.pasta, id_caso, repeticao)  # uma chamada paga por execução terminada
            return legitima_reparada()
        return criar

    def sessao(self, criar, anteriores=None, repeticoes=2, oraculo=ORACULO, commits=COMMITS) -> int:
        with redirect_stdout(io.StringIO()) as saida, redirect_stderr(io.StringIO()):
            codigo = runner.executar_rodada(self.casos, self.oraculo, self.api, "base", self.pasta, repeticoes,
                                            criar, commits, MavenFalso(), aquecer_antes=False, oraculo=oraculo,
                                            anteriores=anteriores, tratamentos=("agentes",))
        self.saida = saida.getvalue()
        return codigo

    def interromper(self, em=("A1-002", 1)) -> None:
        """Primeira sessão: A1-001 r1 e r2 terminam, e a rodada cai no meio do A1-002 r1."""
        with self.assertRaises(Interrompido):
            self.sessao(self.fabrica(cair_em=em))

    def retomar(self, cab=None) -> runner.Anteriores:
        return runner.carregar_anteriores(self.pasta, True, cab or runner.cabecalho("base", ORACULO, COMMITS,
                                                                                    runner.LIMITE_CASO_S))

    def log(self) -> dict:
        return json.loads((self.pasta / runner.ARQUIVO_LOG).read_text(encoding="utf-8"))

    def chaves(self) -> list[tuple]:
        return [runner.chave(r) for r in self.resultados()]


# ---------------------------------------------------------------- a. pula o que já está gravado

class TestAPulaOQueJaEstaGravado(BaseRetomada):
    def test_so_roda_o_que_falta_sem_repetir_nem_perder(self):
        self.interromper()
        self.assertEqual(self.chaves(), [("A1-001", "agentes", 1), ("A1-001", "agentes", 2)])
        self.criadas.clear()
        self.assertEqual(self.sessao(self.fabrica(), self.retomar()), runner.SAIDA_OK)
        self.assertEqual(self.criadas, [("A1-002", 1), ("A1-002", 2)])  # o A1-001 não rodou de novo
        esperado = [(c, "agentes", r) for c in ("A1-001", "A1-002") for r in (1, 2)]
        self.assertEqual(self.chaves(), esperado)  # cada execução uma vez só, na ordem da D82
        self.assertEqual([runner.chave(x) for x in self.log()["execucoes"]], esperado)
        self.assertIn("retomada: 2 execuções já gravadas, 2 a rodar", self.saida)

    def test_so_no_resultado_e_nao_no_log_roda_de_novo(self):
        # a queda entre gravar os resultados e gravar o log: a execução não conta como feita
        self.sessao(self.fabrica(), repeticoes=1)
        log = self.log()
        log["execucoes"] = log["execucoes"][:1]  # o log perdeu o A1-002 r1, que está nos resultados
        (self.pasta / runner.ARQUIVO_LOG).write_text(json.dumps(log), encoding="utf-8")
        anteriores = self.retomar()
        self.assertEqual(anteriores.feitos(), {("A1-001", "agentes", 1)})
        self.assertEqual([runner.chave(r) for r in anteriores.registros], [("A1-001", "agentes", 1)])
        self.criadas.clear()
        self.sessao(self.fabrica(), anteriores, repeticoes=1)
        self.assertEqual(self.criadas, [("A1-002", 1)])
        self.assertEqual(self.chaves(), [("A1-001", "agentes", 1), ("A1-002", "agentes", 1)])

    def test_tudo_gravado_nao_roda_nada(self):
        self.sessao(self.fabrica(), repeticoes=1)
        self.criadas.clear()
        self.assertEqual(self.sessao(self.fabrica(), self.retomar(), repeticoes=1), runner.SAIDA_OK)
        self.assertEqual(self.criadas, [])
        self.assertIn("nada a rodar", self.saida)

    def test_a_chave_inclui_o_tratamento(self):  # T49 e T51 entram na mesma ordem (D82)
        self.sessao(self.fabrica(), repeticoes=1)
        self.assertEqual({x["tratamento"] for x in self.log()["execucoes"]}, {"agentes"})
        self.assertEqual({r["tratamento"] for r in self.resultados()}, {"agentes"})

    def test_retomar_numa_pasta_vazia_comeca_do_zero(self):
        self.assertEqual(self.retomar().feitos(), set())


# ---------------------------------------------------------------- b. refaz a execução do meio

class TestBRefazAExecucaoDoMeio(BaseRetomada):
    def test_a_execucao_interrompida_roda_do_inicio(self):
        self.interromper()
        self.assertNotIn(("A1-002", "agentes", 1), self.chaves())  # a do meio não foi gravada
        self.criadas.clear()
        self.sessao(self.fabrica(), self.retomar())
        self.assertEqual(self.criadas[0], ("A1-002", 1))  # nova fábrica: o agente começa do zero
        [r] = [r for r in self.resultados() if runner.chave(r) == ("A1-002", "agentes", 1)]
        self.assertEqual((r["decisao"], r["passou"]), ("reparar", True))

    def test_as_chamadas_pagas_dela_ficam_sem_registro(self):
        self.interromper()
        anteriores = self.retomar()
        self.assertEqual(anteriores.chamadas_sem_registro,
                         [{"id_caso": "A1-002", "tratamento": "agentes", "repeticao": 1, "chamadas": 2,
                           "custo_usd": 0.002}])
        self.sessao(self.fabrica(), anteriores)
        [_, segunda] = self.log()["sessoes"]
        self.assertEqual((segunda["execucoes_ja_gravadas"], segunda["chamadas_sem_registro"][0]["chamadas"]), (2, 2))
        self.assertIn("chamadas pagas sem registro: 2 (US$ 0.002000)", self.saida)
        # o registro da execução refeita só soma as chamadas desta sessão (1), não as 2 perdidas
        [r] = [r for r in self.resultados() if runner.chave(r) == ("A1-002", "agentes", 1)]
        self.assertEqual((r["custo_usd"], r["tokens"]), (0.001, 600))

    def test_cada_chamada_paga_e_contada_uma_vez(self):
        # duas quedas seguidas: o total do chamadas.jsonl = registros + sem registro de todas as sessões
        self.interromper(("A1-001", 2))
        self.sessao_cai = self.retomar()
        with self.assertRaises(Interrompido):
            self.sessao(self.fabrica(cair_em=("A1-002", 1)), self.sessao_cai)
        self.sessao(self.fabrica(), self.retomar())
        sessoes = self.log()["sessoes"]
        self.assertEqual([[(c["id_caso"], c["repeticao"]) for c in s["chamadas_sem_registro"]] for s in sessoes],
                         [[], [("A1-001", 2)], [("A1-002", 1)]])
        sem_registro = sum(c["custo_usd"] for s in sessoes for c in s["chamadas_sem_registro"])
        registrado = sum(r["custo_usd"] for r in self.resultados())
        self.assertAlmostEqual(registrado + sem_registro, gasto_do_log(self.pasta / runner.ARQUIVO_CHAMADAS)[0])
        self.assertEqual(len(self.resultados()), 4)


# ---------------------------------------------------------------- c. orçamento da rodada inteira

class TestSemRegistroPorTratamento(unittest.TestCase):
    """T49: as chamadas pagas sem registro se separam por tratamento no mesmo (caso, repetição)."""

    def linhas(self, *dados) -> list[str]:
        return [json.dumps({"id_caso": i, "repeticao": r, "custo_usd": c, **({"tratamento": t} if t else {})})
                for i, t, r, c in dados]

    def test_a_feita_de_um_tratamento_nao_esconde_a_do_outro(self):
        linhas = self.linhas(("A1-001", "agentes", 1, 0.001), ("A1-001", "agente_unico", 1, 0.002),
                             ("A1-001", "agente_unico", 1, 0.003))
        sem = runner._sem_registro(linhas, {("A1-001", "agentes", 1)})
        self.assertEqual(sem, [{"id_caso": "A1-001", "tratamento": "agente_unico", "repeticao": 1, "chamadas": 2,
                                "custo_usd": 0.005}])

    def test_linha_sem_tratamento_e_dos_agentes(self):  # chamadas.jsonl de antes da T49
        linhas = self.linhas(("A1-001", None, 1, 0.001))
        self.assertEqual(runner._sem_registro(linhas, {("A1-001", "agentes", 1)}), [])
        self.assertEqual(runner._sem_registro(linhas, {("A1-001", "agente_unico", 1)})[0]["tratamento"], "agentes")


class TestCOrcamentoDaRodadaInteira(BaseRetomada):
    def test_a_trava_soma_as_sessoes_anteriores(self):  # D105
        self.interromper()  # 4 chamadas de US$ 0,001: US$ 0,004 gastos
        criar = self.fabrica()

        def com_trava(id_caso, repeticao):
            return runner.com_trava(criar(id_caso, repeticao),
                                    runner.Orcamento(0.004, self.pasta / runner.ARQUIVO_CHAMADAS))
        self.criadas.clear()
        self.assertEqual(self.sessao(com_trava, self.retomar()), runner.SAIDA_ORCAMENTO)
        self.assertEqual(len(self.resultados()), 2)  # nada novo foi gravado

    def test_com_saldo_a_retomada_segue(self):
        self.interromper()

        def com_trava(id_caso, repeticao):
            return runner.com_trava(legitima_reparada(),
                                    runner.Orcamento(0.005, self.pasta / runner.ARQUIVO_CHAMADAS))
        self.assertEqual(self.sessao(com_trava, self.retomar()), runner.SAIDA_OK)


# ---------------------------------------------------------------- d. recusa se mudou a configuração

class TestDRecusaOutraConfiguracao(BaseRetomada):
    def test_cada_mudanca_e_recusada(self):
        self.sessao(self.fabrica(), repeticoes=1)
        limites = runner.cabecalho("base", ORACULO, COMMITS, runner.LIMITE_CASO_S)["limites"]
        mudancas = {
            "tag": runner.cabecalho("outra", ORACULO, COMMITS, runner.LIMITE_CASO_S),
            "oráculo (arquivo)": runner.cabecalho("base", {**ORACULO, "arquivo": "casos/x.json"}, COMMITS,
                                                  runner.LIMITE_CASO_S),
            "oráculo (commit)": runner.cabecalho("base", {**ORACULO, "commit": "o2"}, COMMITS, runner.LIMITE_CASO_S),
            "prompts": runner.cabecalho("base", ORACULO, ("p2", "c"), runner.LIMITE_CASO_S),
            "código": runner.cabecalho("base", ORACULO, ("p", "c2"), runner.LIMITE_CASO_S),
            "limite do caso": runner.cabecalho("base", ORACULO, COMMITS, 90),
            "limite do teste": {**runner.cabecalho("base", ORACULO, COMMITS, runner.LIMITE_CASO_S),
                                "limites": {**limites, "teste_s": 60}},
            "limite do LLM": {**runner.cabecalho("base", ORACULO, COMMITS, runner.LIMITE_CASO_S),
                              "limites": {**limites, "llm_s": 60}},
        }
        for nome, cab in mudancas.items():
            with self.subTest(nome):
                with self.assertRaises(runner.RetomadaInvalida):
                    self.retomar(cab)
        self.retomar()  # sem mudança, aceita

    def test_resultados_sem_log_sao_recusados(self):
        self.sessao(self.fabrica(), repeticoes=1)
        (self.pasta / runner.ARQUIVO_LOG).unlink()
        with self.assertRaises(runner.RetomadaInvalida):
            self.retomar()

    def test_log_de_antes_da_t53_e_recusado(self):  # sem o oráculo no log, não dá para conferir
        self.sessao(self.fabrica(), repeticoes=1, oraculo=None)
        with self.assertRaises(runner.RetomadaInvalida):
            self.retomar()


# ---------------------------------------------------------------- main: sem ler a chave

class BaseMain(BaseRetomada):
    """O `main` com o oráculo, os commits e a API falsos. A chave nunca pode ser lida."""

    def setUp(self):
        super().setUp()
        self.do_oraculo = dict(ORACULO)
        self.commits = COMMITS
        arquivo = self.raiz / "casos" / "oraculo.json"
        arquivo.parent.mkdir()
        arquivo.write_text(json.dumps({"versao_api": "base", "casos": [
            {**self.oraculo[c.id_caso], "teste_afetado": "ProdutoTest.busca", "patch": str(c.patch)}
            for c in self.casos]}), encoding="utf-8")
        for alvo, valor in (("RAIZ_REPO", self.raiz), ("oraculo_do_log", lambda a: dict(self.do_oraculo)),
                            ("commits_atuais", lambda: self.commits)):
            p = mock.patch.object(runner, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(runner.cliente_claude, "ler_chave", side_effect=AssertionError("leu a chave"))
        self.ler_chave = p.start()
        self.addCleanup(p.stop)

    def main(self, *extra: str, sdk=None) -> int:
        argv = ["--api", str(self.api), "--saida", str(self.pasta), "--orcamento-usd", "0.004", "--repeticoes",
                "2", "--tag", "base", "--sim", "--tratamentos", "agentes", *extra]
        with redirect_stdout(io.StringIO()) as saida, redirect_stderr(io.StringIO()) as erro:
            codigo = runner.main(argv, sdk=sdk, rodar=MavenFalso())
        self.saida, self.erro = saida.getvalue(), erro.getvalue()
        return codigo


class TestDMainRecusaSemLerAChave(BaseMain):
    def setUp(self):
        super().setUp()
        self.interromper()

    def recusa(self, *extra: str) -> None:
        self.assertEqual(self.main("--retomar", *extra), 2)
        self.assertIn("outra configuração", self.erro)
        self.ler_chave.assert_not_called()
        self.assertEqual(len(self.resultados()), 2)

    def test_outro_oraculo(self):
        final = self.raiz / "casos" / "oraculo-final.json"
        final.write_bytes((self.raiz / "casos" / "oraculo.json").read_bytes())  # mesmo conteúdo, outro arquivo
        self.do_oraculo = {"arquivo": "casos/oraculo-final.json", "commit": "o1"}
        self.recusa()

    def test_outro_commit_do_oraculo(self):
        self.do_oraculo["commit"] = "o2"
        self.recusa()

    def test_outros_prompts(self):
        self.commits = ("p2", "c")
        self.recusa()

    def test_outro_codigo(self):
        self.commits = ("p", "c2")
        self.recusa()

    def test_outro_limite(self):
        with mock.patch.object(runner, "LIMITE_CASO_S", 90):
            self.recusa()

    def test_outra_tag(self):
        self.oraculo_tag = json.loads((self.raiz / "casos" / "oraculo.json").read_text(encoding="utf-8"))
        self.oraculo_tag["versao_api"] = "outra"
        (self.raiz / "casos" / "oraculo.json").write_text(json.dumps(self.oraculo_tag), encoding="utf-8")
        self.assertEqual(self.main("--retomar", "--tag", "outra"), 2)
        self.ler_chave.assert_not_called()

    def test_a_trava_do_main_vale_para_a_rodada_inteira(self):  # c, pelo main: US$ 0,004 já gastos
        self.assertEqual(self.main("--retomar", sdk=object()), runner.SAIDA_ORCAMENTO)
        self.assertIn("já gastos US$ 0.004000 nesta pasta", self.saida)
        self.assertIn("com as sessões anteriores desta pasta", self.saida)
        self.assertEqual(len(self.resultados()), 2)


# ---------------------------------------------------------------- e. sem --retomar, recusa

class TestESemRetomarRecusa(BaseMain):
    def test_pasta_com_rodada_e_recusada_sem_ler_a_chave(self):
        self.interromper()
        self.assertEqual(self.main(), 2)
        self.assertIn("use --retomar", self.erro)
        self.ler_chave.assert_not_called()

    def test_basta_um_dos_tres_arquivos(self):
        for nome in (runner.ARQUIVO_RESULTADOS, runner.ARQUIVO_LOG, runner.ARQUIVO_CHAMADAS):
            with self.subTest(nome), tempfile.TemporaryDirectory() as d:
                (Path(d) / nome).write_text("{}", encoding="utf-8")
                with self.assertRaises(runner.RetomadaInvalida):
                    runner.carregar_anteriores(Path(d), False, {})

    def test_pasta_nova_passa_da_conferencia(self):
        runner.carregar_anteriores(self.pasta, False, {})  # não levanta


# ---------------------------------------------------------------- --oraculo

class TestOraculo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        git = lambda *a: subprocess.run(["git", *a], cwd=self.raiz, check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (self.raiz / "casos").mkdir()
        self.arquivo = self.raiz / "casos" / "oraculo-final.json"
        self.arquivo.write_text("{}", encoding="utf-8")
        git("add", ".")
        git("commit", "-q", "-m", "oráculo")
        self.commit = subprocess.run(["git", "log", "-1", "--format=%H"], cwd=self.raiz, capture_output=True,
                                     text=True).stdout.strip()

    def test_arquivo_relativo_e_commit(self):
        self.assertEqual(runner.oraculo_do_log(self.arquivo, self.raiz),
                         {"arquivo": "casos/oraculo-final.json", "commit": self.commit})

    def test_mudanca_nao_gravada_e_recusada(self):  # como os prompts e o código (D105)
        self.arquivo.write_text('{"mudou": 1}', encoding="utf-8")
        with self.assertRaises(runner.OraculoInvalido):
            runner.oraculo_do_log(self.arquivo, self.raiz)

    def test_arquivo_novo_sem_commit_e_recusado(self):
        novo = self.raiz / "casos" / "novo.json"
        novo.write_text("{}", encoding="utf-8")
        with self.assertRaises(runner.OraculoInvalido):
            runner.oraculo_do_log(novo, self.raiz)

    def test_fora_do_repositorio_e_recusado(self):
        with tempfile.TemporaryDirectory() as fora:
            (Path(fora) / "o.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(runner.OraculoInvalido):
                runner.oraculo_do_log(Path(fora) / "o.json", self.raiz)

    def test_o_padrao_e_o_do_piloto(self):
        args = runner._argumentos(["--api", "a", "--saida", "s", "--orcamento-usd", "0.1"])
        self.assertEqual(args.oraculo, runner.RAIZ_REPO / "casos" / "oraculo-agente1.json")
        self.assertFalse(args.retomar)

    def test_os_dois_oraculos_do_repositorio(self):
        for nome in ("oraculo-agente1.json", "oraculo-agente1-final.json"):
            with self.subTest(nome):
                do_log = runner.oraculo_do_log(runner.RAIZ_REPO / "casos" / nome)
                self.assertEqual(do_log["arquivo"], f"casos/{nome}")
                self.assertEqual(len(do_log["commit"]), 40)


class TestOraculoNoLog(BaseMain):
    def test_o_log_da_sessao_grava_o_arquivo_e_o_commit(self):
        self.do_oraculo = {"arquivo": "casos/oraculo.json", "commit": "o9"}
        with mock.patch.object(runner.Orcamento, "verificar", side_effect=runner.OrcamentoEsgotado(0, 1)):
            self.assertEqual(self.main(sdk=object()), runner.SAIDA_ORCAMENTO)  # para antes da 1ª chamada
        self.assertEqual(self.log()["oraculo"], {"arquivo": "casos/oraculo.json", "commit": "o9"})
        self.assertIn("oráculo: casos/oraculo.json (commit o9)", self.saida)


if __name__ == "__main__":
    unittest.main()
