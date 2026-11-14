"""A baseline no runner (T51), com o Maven simulado: nada aqui chama o LLM nem a API paga.

Usa a API cobaia falsa de test_rodar.py: o patch renomeia `sku` para `codigo` na resposta, e a baseline
renomeia a asserção `$.sku` para `$.codigo` (D75).
"""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agente_contrato import rodar as runner
from agente_contrato.guarda import Veredito
from tests.relogio_falso import RelogioFalso
from tests.test_retomada import BaseMain
from tests.test_rodar import Base, MavenFalso, legitima_reparada


def nunca(id_caso, repeticao):
    raise AssertionError("a baseline não pode criar modelo")


class TestExecutarBaseline(Base):
    def executar(self, maven=None, **kw):
        with redirect_stdout(io.StringIO()):
            return runner.executar_baseline(self.caso, self.api, "base", self.raiz / "copia", maven or MavenFalso(),
                                            **kw)

    def test_renomeacao_reparada_e_conferida_no_maven_final(self):
        e, b = self.executar()
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", None, True, True))
        self.assertIn('jsonPath("$.codigo")', e.depois)
        self.assertIn('jsonPath("$.sku")', e.antes)
        self.assertEqual(len(b.aplicadas), 1)
        self.assertIn("sku", b.aplicadas[0])

    def test_recusa_do_guarda_nao_grava_e_nao_roda_o_maven_final(self):  # D74: erro guarda, como na v1
        maven = MavenFalso()
        with mock.patch.object(runner, "guarda_do_caso", lambda *a: lambda texto: Veredito(False, ("motivo x",))):
            e, b = self.executar(maven)
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("nao_reparar", "guarda", None, False))
        self.assertEqual(e.antes, e.depois)
        self.assertEqual(b.recusas_do_guarda, ("motivo x",))
        self.assertEqual(len(maven.limites), 1)  # só o Maven inicial

    def test_diferenca_que_nao_atinge_o_teste_nao_repara(self):
        with mock.patch.object(runner, "rotas_do_contrato", lambda contrato: {"GET": {"/outra/{id}"}}):
            e, b = self.executar()
        self.assertEqual((e.fim.decisao, e.fim.erro, e.antes == e.depois), ("nao_reparar", None, True))
        self.assertEqual(b.ignoradas[0][1], "a mudança não atinge o teste")

    def test_estouro_do_maven_final_e_timeout(self):  # D111d, D118
        e, _ = self.executar(MavenFalso("normal", "estouro"))
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", "timeout", False, False))

    def test_maven_final_usa_o_menor_entre_120_s_e_o_que_resta_do_caso(self):  # D111, D123
        relogio = RelogioFalso()
        maven = MavenFalso(relogio=relogio, passo_s=100)  # o Maven inicial fica fora do relógio do caso (D118)
        self.executar(maven, agora=relogio)
        self.assertEqual(maven.limites, [120, 120])
        maven = MavenFalso()
        self.executar(maven, limite_caso_s=50, agora=RelogioFalso())
        self.assertEqual(maven.limites, [120, 50])

    def test_tempo_conta_o_maven_final_como_nos_agentes(self):  # D133
        relogio = RelogioFalso()
        e, _ = self.executar(MavenFalso(relogio=relogio, passo_s=10), agora=relogio)
        self.assertEqual(e.tempo_s, 10)  # o Maven inicial fica fora (D118); o final entra
        relogio = RelogioFalso()
        with mock.patch.object(runner, "guarda_do_caso", lambda *a: lambda texto: Veredito(False, ("x",))):
            e, _ = self.executar(MavenFalso(relogio=relogio, passo_s=10), agora=relogio)
        self.assertEqual(e.tempo_s, 0)  # sem reparo aceito, não há Maven final

    def test_teste_que_passa_sem_reparo_e_erro_de_execucao(self):  # D111e
        with redirect_stdout(io.StringIO()):
            e, _ = runner.baseline_do_caso(self.caso, 1, self.api, "base", self.raiz, MavenFalso("passa"))
        self.assertEqual((e.fim.erro, e.causa), ("erro_execucao", "teste_passa_sem_reparo"))

    def test_a_copia_e_apagada(self):
        self.executar()
        self.assertFalse((self.raiz / "copia").exists())


class TestRodadaComBaseline(Base):
    def rodar(self, criar=lambda i, r: legitima_reparada(), repeticoes=2, **kw) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return runner.executar_rodada([self.caso], self.oraculo, self.api, "base", self.pasta, repeticoes, criar,
                                          ("p", "c"), MavenFalso(), aquecer_antes=False, **kw)

    def test_baseline_antes_dos_agentes_e_uma_repeticao_so(self):  # D82, D92
        self.assertEqual(self.rodar(), runner.SAIDA_OK)
        self.assertEqual([(r["tratamento"], r["versao_agente"], r["repeticao"]) for r in self.resultados()],
                         [("baseline", None, 1), ("agentes", "agentica", 1), ("agentes", "agentica", 2)])

    def test_registro_da_baseline_sem_tokens_nem_custo(self):
        self.rodar(tratamentos=("baseline",), criar=nunca)
        [r] = self.resultados()
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"], r["tokens"], r["custo_usd"]),
                         ("reparar", True, True, None, 0, 0.0))
        self.assertEqual((r["equivalente_oraculo"], r["cenario_alterado"]), (None, None))  # sem o comparador (T50)

    def test_log_e_pasta_por_execucao(self):  # D89, D105
        self.rodar(tratamentos=("baseline",), criar=nunca)
        log = json.loads((self.pasta / runner.ARQUIVO_LOG).read_text(encoding="utf-8"))
        [x] = log["execucoes"]
        self.assertEqual((x["tratamento"], x["commit_do_codigo"], x["commit_do_prompt"]), ("baseline", "c", None))
        self.assertEqual(len(x["aplicadas"]), 1)
        self.assertEqual(log["sessoes"][0]["tratamentos"], ["baseline"])
        pasta = self.pasta / "execucoes" / "A1-001-baseline-r1"
        self.assertIn("$.codigo", (pasta / "reparo.diff").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((pasta / "log.json").read_text(encoding="utf-8")), x)

    def test_retomada_pula_a_baseline_ja_gravada(self):  # T53
        self.rodar(tratamentos=("baseline",), criar=nunca)
        cab = runner.cabecalho("base", None, ("p", "c"), runner.LIMITE_CASO_S)
        anteriores = runner.carregar_anteriores(self.pasta, True, {**cab, "oraculo": None})
        self.assertEqual(anteriores.feitos(), {("A1-001", "baseline", 1)})
        self.rodar(anteriores=anteriores)
        self.assertEqual([r["tratamento"] for r in self.resultados()], ["baseline", "agentes", "agentes"])

    def test_erro_de_infraestrutura_da_baseline_entra_nas_exclusoes(self):  # D111e
        with redirect_stdout(io.StringIO()):
            runner.executar_rodada([self.caso], self.oraculo, self.api, "base", self.pasta, 1, nunca, ("p", "c"),
                                   MavenFalso("passa"), aquecer_antes=False, tratamentos=("baseline",))
        log = json.loads((self.pasta / runner.ARQUIVO_LOG).read_text(encoding="utf-8"))
        self.assertEqual(log["exclusoes"], [{"id_caso": "A1-001", "tratamento": "baseline", "repeticao": 1,
                                             "erro": "erro_execucao", "causa": "teste_passa_sem_reparo"}])


class TestMainSoBaseline(BaseMain):
    def main_baseline(self, *extra) -> int:
        argv = ["--api", str(self.api), "--saida", str(self.pasta), "--tag", "base", "--tratamentos", "baseline",
                *extra]
        with redirect_stdout(io.StringIO()) as saida, redirect_stderr(io.StringIO()) as erro, \
                mock.patch("builtins.input", side_effect=AssertionError("pediu confirmação")):
            codigo = runner.main(argv, rodar=MavenFalso())
        self.saida, self.erro = saida.getvalue(), erro.getvalue()
        return codigo

    def test_sem_chave_sem_orcamento_e_sem_confirmacao(self):
        self.assertEqual(self.main_baseline(), runner.SAIDA_OK)
        self.ler_chave.assert_not_called()
        registros = json.loads((self.pasta / runner.ARQUIVO_RESULTADOS).read_text(encoding="utf-8"))["execucoes"]
        self.assertEqual({r["tratamento"] for r in registros}, {"baseline"})
        self.assertEqual(len(registros), len(self.casos))  # 1 repetição (D92), mesmo com --repeticoes 3 padrão
        self.assertFalse((self.pasta / runner.ARQUIVO_CHAMADAS).exists())

    def test_com_agentes_o_orcamento_e_obrigatorio(self):  # D105
        argv = ["--api", str(self.api), "--saida", str(self.pasta), "--tag", "base"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as erro:
            self.assertEqual(runner.main(argv, rodar=MavenFalso()), 2)
        self.assertIn("--orcamento-usd", erro.getvalue())
        self.ler_chave.assert_not_called()


if __name__ == "__main__":
    unittest.main()
