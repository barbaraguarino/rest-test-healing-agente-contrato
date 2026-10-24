import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato import chamada_llm, execucao, registro_llm, resultados
from agente_contrato import rodar_v1 as v1
from agente_contrato.chamada_llm import ErroDeRede, ErroFatal
from agente_contrato.rodar_baseline import Entrada
from agente_contrato.registro_llm import LogDeChamadas, Orcamento

from . import api_falsa as af
from .fakes import ClienteFalso, RelogioFalso, classificacao, reparo, resposta

TEXTOS = {"classifier": "SISTEMA CLASSIFIER", "repair": "SISTEMA REPAIR"}
CUSTO_UMA_CHAMADA = registro_llm.custo_usd(registro_llm.Uso(6000, 500, None))


class BaseRodada(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)
        self.api = af.criar(self.pasta)
        self.entrada = Entrada("A1-901", self.api.patch, af.CLASSE, af.METODO)
        self.saida = self.pasta / "saida"

    def rodar(self, roteiro, oraculo=None, repeticoes=1, limite=0.10, rodar=None, commit_codigo="def456"):
        self.cliente = ClienteFalso(roteiro)
        self.orcamento = Orcamento(limite)
        self.log = LogDeChamadas(self.saida / "chamadas.jsonl")
        chamador = v1.Chamador(self.cliente, self.log, self.orcamento, TEXTOS, "abc123")
        oraculo = oraculo or af.ORACULO_LEGITIMO
        codigo = v1.executar_rodada([self.entrada], {"A1-901": oraculo}, self.api.api, af.TAG, self.api.raiz_repo,
                                    self.saida, repeticoes, chamador, rodar or af.RodarFalso(), commit_codigo)
        return codigo

    def registros(self):
        arquivo = self.saida / "resultados-agente1.json"
        return json.loads(arquivo.read_text(encoding="utf-8"))["execucoes"] if arquivo.exists() else []

    def resumo(self):
        return json.loads((self.saida / "log-v1.json").read_text(encoding="utf-8"))["execucoes"]

    def linhas_do_log(self):
        arquivo = self.saida / "chamadas.jsonl"
        return [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines()] if arquivo.exists() else []


class CaminhoFelizTest(BaseRodada):
    def test_caso_legitimo_reparado(self):
        codigo = self.rodar([classificacao("legitima"), reparo(af.metodo_certo())])
        self.assertEqual(codigo, v1.SAIDA_OK)
        (r,) = self.registros()
        self.assertEqual(resultados.problemas(r), [])
        self.assertEqual((r["tratamento"], r["versao_agente"], r["decisao"], r["compilou"], r["passou"],
                          r["equivalente_oraculo"], r["erro"]), ("agentes", "v1", "reparar", True, True, True, None))
        self.assertEqual(r["tokens"], 2 * 6500)
        self.assertAlmostEqual(r["custo_usd"], 2 * CUSTO_UMA_CHAMADA, places=8)

    def test_o_log_tem_uma_linha_por_chamada_com_o_commit_do_prompt(self):
        self.rodar([classificacao("legitima"), reparo(af.metodo_certo())])
        linhas = self.linhas_do_log()
        self.assertEqual([l["etapa"] for l in linhas], ["classifier", "repair"])
        self.assertTrue(all(l["commit_do_prompt"] == "abc123" and l["request_id"] == "req_falso" for l in linhas))
        self.assertEqual(self.resumo()[0]["rotulo_classifier"], "legitima")

    def test_o_resumo_grava_o_commit_do_codigo(self):
        self.rodar([classificacao("legitima"), reparo(af.metodo_certo())])
        self.assertEqual(self.resumo()[0]["commit_do_codigo"], "def456")

    def test_commit_do_codigo_e_o_hash_da_pasta_do_codigo(self):
        self.assertRegex(v1.commit_do_codigo(), r"^[0-9a-f]{40}(\+alterado)?$")

    def test_regressao_nao_chama_o_repair(self):
        self.rodar([classificacao("problema_real")], oraculo=af.ORACULO_REGRESSAO)
        (r,) = self.registros()
        self.assertEqual((r["decisao"], r["passou"], r["compilou"], r["erro"], r["rotulo_oraculo"]),
                         ("nao_reparar", False, None, None, "problema_real"))
        self.assertEqual(len(self.cliente.chamadas), 1)
        self.assertEqual(r["tokens"], 6500)

    def test_o_llm_nao_recebe_nada_do_oraculo_nem_dos_casos(self):
        self.rodar([classificacao("legitima"), reparo(af.metodo_certo())])
        for sistema, usuario, _ in self.cliente.chamadas:
            for proibido in ("A1-901", "esperado", "rotulo_oraculo", "correcao_esperada", "casos/"):
                self.assertNotIn(proibido, sistema + usuario)
            self.assertIn("$.descricao", usuario)           # o teste afetado
            self.assertIn("No value at JSON path", usuario)  # a mensagem de falha
            self.assertIn("resumo", usuario)                 # o código e o contrato novos


class SaidasRejeitadasTest(BaseRodada):
    def _erro(self, roteiro):
        self.rodar(roteiro)
        (r,) = self.registros()
        self.assertEqual((r["decisao"], r["passou"], r["compilou"]), ("nao_reparar", False, None))
        return r["erro"]

    def test_json_invalido_no_classifier(self):
        self.assertEqual(self._erro([resposta("não é json")]), "saida_invalida")
        self.assertEqual(len(self.cliente.chamadas), 1)  # sem Repair e sem nova tentativa (D102)

    def test_max_tokens_no_repair_guarda_o_rotulo_so_no_log(self):
        self.assertEqual(self._erro([classificacao("legitima"), resposta('{"metodo_reparado": "x', "max_tokens")]),
                         "max_tokens")
        self.assertEqual(self.resumo()[0]["rotulo_classifier"], "legitima")

    def test_refusal_no_repair(self):
        self.assertEqual(self._erro([classificacao("legitima"), resposta(None, "refusal")]), "saida_invalida")

    def test_estouro_de_contexto(self):
        self.assertEqual(self._erro([resposta(None, "model_context_window_exceeded")]), "saida_invalida")

    def test_metodo_que_nao_encaixa(self):
        self.assertEqual(self._erro([classificacao("legitima"), reparo("void outroNome() { }")]), "saida_invalida")
        self.assertIn("não encaixa", self.resumo()[0]["motivo_erro"])

    def test_o_guarda_recusa_reparo_que_tira_asserção(self):
        self.assertEqual(self._erro([classificacao("legitima"), reparo(af.metodo_sem_uma_assercao())]), "guarda")
        self.assertTrue(self.resumo()[0]["guarda"])


class ResultadoDoReparoTest(BaseRodada):
    def test_reparo_que_nao_compila_nao_e_erro(self):
        self.rodar([classificacao("legitima"), reparo(af.metodo_que_nao_compila())])
        (r,) = self.registros()
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"]), ("reparar", False, False, None))

    def test_reparo_que_compila_e_nao_passa(self):
        self.rodar([classificacao("legitima"), reparo(af.metodo_original())])
        (r,) = self.registros()
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"]), ("reparar", True, False, None))


class RedeETravasTest(BaseRodada):
    def test_erro_de_rede_reexecuta_o_caso_e_conta_o_gasto_das_duas_tentativas(self):
        self.rodar([classificacao("legitima"), ErroDeRede("HTTP 500", 0.2),
                    classificacao("legitima"), reparo(af.metodo_certo())])
        (r,) = self.registros()
        self.assertEqual((r["erro"], r["passou"]), (None, True))
        self.assertEqual(self.resumo()[0]["tentativas"], 2)
        self.assertEqual(r["tokens"], 3 * 6500)  # o Classifier da primeira tentativa também foi pago
        linhas = self.linhas_do_log()
        self.assertEqual(len(linhas), 4)
        self.assertIn("ErroDeRede", linhas[1]["erro"])
        self.assertEqual(linhas[1]["custo_usd"], 0.0)

    def test_duas_falhas_de_rede_viram_erro_llm(self):
        self.rodar([ErroDeRede("timeout", 120.0), ErroDeRede("timeout", 120.0)])
        (r,) = self.registros()
        self.assertEqual((r["erro"], r["decisao"], r["passou"], r["tokens"]), ("erro_llm", "nao_reparar", False, 0))

    def test_tres_erro_llm_seguidos_param_a_rodada(self):
        codigo = self.rodar([ErroDeRede("x", 1.0)] * 10, repeticoes=5)
        self.assertEqual(codigo, v1.SAIDA_ERROS_SEGUIDOS)
        self.assertEqual(len(self.registros()), 3)

    def test_erro_llm_nao_seguido_zera_a_contagem(self):
        ruim, bom = [ErroDeRede("x", 1.0)] * 2, [classificacao("problema_real")]
        codigo = self.rodar(ruim + bom + ruim + ruim, oraculo=af.ORACULO_REGRESSAO, repeticoes=4)
        self.assertEqual(codigo, v1.SAIDA_OK)
        self.assertEqual([r["erro"] for r in self.registros()], ["erro_llm", None, "erro_llm", "erro_llm"])

    def test_erro_fatal_para_e_nao_grava_o_caso(self):
        codigo = self.rodar([ErroFatal("HTTP 400: limite de gasto", 0.1)])
        self.assertEqual(codigo, v1.SAIDA_ERRO_FATAL)
        self.assertEqual(self.registros(), [])
        self.assertIn("ErroFatal", self.linhas_do_log()[0]["erro"])

    def test_orcamento_esgotado_para_antes_da_proxima_chamada(self):
        codigo = self.rodar([classificacao("legitima"), reparo(af.metodo_certo())], repeticoes=2, limite=0.001)
        self.assertEqual(codigo, v1.SAIDA_ORCAMENTO)
        self.assertEqual(len(self.registros()), 1)       # a repetição 1 ficou completa
        self.assertEqual(len(self.cliente.chamadas), 2)  # nenhuma chamada além do limite

    def test_teste_que_passa_sem_reparo_e_erro_de_execucao_sem_gastar(self):
        self.rodar([], rodar=af.RodarFalso(ja_passa=True))
        (r,) = self.registros()
        self.assertEqual((r["erro"], r["tokens"]), ("erro_execucao", 0))
        self.assertEqual(self.cliente.chamadas, [])


class LimitesDeTempoTest(BaseRodada):
    """D111 com relógio simulado: o Maven e o LLM só "demoram" no RelogioFalso."""

    def rodar_com_relogio(self, roteiro, duracoes, espera_llm_s=2.0, oraculo=None, caso_s=180):
        self.relogio = RelogioFalso()
        self.rodar_falso = af.RodarFalso(duracoes=duracoes, relogio=self.relogio)
        self.cliente = ClienteFalso(roteiro, self.relogio, espera_llm_s)
        chamador = v1.Chamador(self.cliente, LogDeChamadas(self.saida / "chamadas.jsonl"), Orcamento(0.10),
                               TEXTOS, "abc123")
        limites = execucao.Limites(caso_s=caso_s, llm_s=120, relogio=self.relogio)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            codigo = v1.executar_rodada([self.entrada], {"A1-901": oraculo or af.ORACULO_LEGITIMO}, self.api.api,
                                        af.TAG, self.api.raiz_repo, self.saida, 1, chamador, self.rodar_falso,
                                        "def456", limites)
        self.console = out.getvalue()
        self.assertEqual(codigo, v1.SAIDA_OK)
        (r,) = self.registros()
        self.assertEqual(resultados.problemas(r), [])
        return r, json.loads((self.saida / "log-v1.json").read_text(encoding="utf-8"))

    def test_estouro_do_teste_final_e_timeout_sem_reexecucao(self):
        r, log = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [10, 500])
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"]), ("reparar", False, False, "timeout"))
        self.assertEqual(log["execucoes"][0]["estouro"], "teste_final")
        self.assertEqual(self.rodar_falso.timeouts, [120, 120])  # o inicial e o final, sem terceira vez
        self.assertEqual(len(self.cliente.chamadas), 2)

    def test_estouro_do_caso_no_teste_final(self):
        r, log = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [10, 110],
                                        caso_s=100)
        self.assertEqual((r["decisao"], r["erro"]), ("reparar", "timeout"))
        self.assertEqual(log["execucoes"][0]["estouro"], "caso")
        self.assertEqual(self.rodar_falso.timeouts[-1], 100)  # o que restava do caso, menor que 120

    def test_a_espera_do_llm_nao_conta_no_caso(self):
        r, log = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [10, 30],
                                        espera_llm_s=170)
        self.assertEqual((r["passou"], r["erro"]), (True, None))
        x = log["execucoes"][0]
        self.assertEqual((x["duracao_caso_s"], x["espera_llm_s"], x["estouro"]), (30, 340, None))

    def test_caso_estourado_antes_de_uma_chamada_nao_chama_o_llm(self):
        r, log = self.rodar_com_relogio([], [10], caso_s=0)
        self.assertEqual((r["decisao"], r["erro"]), ("nao_reparar", "timeout"))
        self.assertEqual((log["execucoes"][0]["estouro"], self.cliente.chamadas), ("caso", []))

    def test_estouro_do_maven_inicial_roda_o_maven_mais_uma_vez(self):
        r, log = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [500, 10, 10])
        self.assertEqual((r["passou"], r["erro"]), (True, None))
        self.assertEqual(log["execucoes"][0]["tentativas_maven_inicial"], 2)
        self.assertEqual(log["exclusoes"], [])

    def test_dois_estouros_do_maven_inicial_excluem_o_caso_e_o_log_lista(self):
        r, log = self.rodar_com_relogio([], [500, 500])
        self.assertEqual((r["decisao"], r["erro"], r["tokens"]), ("nao_reparar", "erro_execucao", 0))
        self.assertEqual(self.cliente.chamadas, [])
        self.assertEqual(log["exclusoes"], [{"id_caso": "A1-901", "repeticao": 1, "erro": "erro_execucao",
                                             "causa": "estouro_maven_inicial"}])
        self.assertEqual(log["exclusoes_por_causa"], {"estouro_maven_inicial": 1})
        self.assertEqual(log["execucoes"][0]["estouro"], "maven_inicial")
        self.assertIn("exclusões (fora das métricas): 1 (estouro_maven_inicial: 1)", self.console)

    def test_o_log_registra_os_limites_usados(self):
        _, log = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [10, 10])
        self.assertEqual(log["limites"], {"teste_s": 120, "caso_s": 180, "llm_s": 120})
        self.assertIn("limites: teste 120 s, caso 180 s, chamada ao LLM 120 s", self.console)

    def test_o_caso_que_estoura_e_falha_do_tratamento(self):
        """Numa regressão, o reparo que estoura conta como reparo (FP), e não como acerto (VN)."""
        r, _ = self.rodar_com_relogio([classificacao("legitima"), reparo(af.metodo_certo())], [10, 500],
                                      oraculo=af.ORACULO_REGRESSAO)
        self.assertEqual((r["rotulo_oraculo"], r["decisao"], r["passou"], r["erro"]),
                         ("problema_real", "reparar", False, "timeout"))
        self.assertNotIn(r["erro"], ("erro_execucao", "erro_llm"))  # entra nas métricas


class EtapasETest(BaseRodada):
    def _chamador(self, roteiro):
        self.cliente = ClienteFalso(roteiro)
        self.log = LogDeChamadas(self.saida / "chamadas.jsonl")
        return v1.Chamador(self.cliente, self.log, Orcamento(0.10), TEXTOS, "abc123")

    def test_etapa_1_conta_tokens_dos_dois_prompts_sem_chamar_o_modelo(self):
        cliente = ClienteFalso([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            codigo = v1.etapa_1([self.entrada], self.api.api, af.TAG, cliente, TEXTOS, "abc123", self.saida,
                                af.RodarFalso())
        self.assertEqual(codigo, v1.SAIDA_OK)
        self.assertIn("A1-901 classifier:", out.getvalue())
        self.assertIn("A1-901 repair:", out.getvalue())
        self.assertEqual(cliente.chamadas, [])

    def test_etapa_1_grava_a_contagem_na_pasta_de_saida(self):
        with contextlib.redirect_stdout(io.StringIO()):
            v1.etapa_1([self.entrada], self.api.api, af.TAG, ClienteFalso([]), TEXTOS, "abc123", self.saida,
                       af.RodarFalso())
        dados = json.loads((self.saida / "contagem-de-tokens.json").read_text(encoding="utf-8"))
        self.assertEqual((dados["modelo"], dados["commit_dos_prompts"]), ("claude-haiku-5-5", "abc123"))
        self.assertRegex(dados["data_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertEqual([(c["id_caso"], c["prompt"]) for c in dados["contagens"]],
                         [("A1-901", "classifier"), ("A1-901", "repair")])
        for c in dados["contagens"]:
            self.assertGreater(c["tokens_de_entrada"], 0)
            self.assertGreater(c["caracteres"], 0)
            self.assertGreater(c["custo_so_da_entrada_usd"], 0)

    def test_etapa_2_mostra_o_que_a_d105_manda_verificar(self):
        chamador = self._chamador([classificacao("legitima", thinking=300, saida=700)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            codigo = v1.etapa_2(self.entrada, self.api.api, af.TAG, chamador, af.RodarFalso())
        texto = out.getvalue()
        self.assertEqual(codigo, v1.SAIDA_OK)
        for esperado in ("stop_reason      : end_turn", "request_id       : req_falso", "thinking_tokens  : 300",
                         "o thinking está dentro da saída", "validação        : OK"):
            self.assertIn(esperado, texto)
        self.assertEqual(len(self.linhas_do_log()), 1)


class NotaDoThinkingTest(unittest.TestCase):
    def _nota(self, thinking, saida=164):
        return v1._nota_do_thinking(registro_llm.Uso(8619, saida, thinking))

    def test_so_confirma_quando_ha_thinking_para_medir(self):
        self.assertIn("dentro da saída", self._nota(300, 700))

    def test_zero_nao_confirma_nada(self):
        nota = self._nota(0)
        self.assertIn("NÃO confirma", nota)
        self.assertNotIn("dentro da saída", nota)

    def test_sem_informacao_da_api(self):
        self.assertIn("não informou", self._nota(None))

    def test_thinking_maior_que_a_saida_e_um_alerta(self):
        self.assertIn("ATENÇÃO", self._nota(900, 700))


class LinhaDeComandoTest(unittest.TestCase):
    def test_etapas_pagas_exigem_orcamento(self):
        for etapa in ("2", "3"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                v1._argumentos(["--etapa", etapa, "--api", "a", "--saida", "s"])

    def test_etapa_1_nao_precisa_de_orcamento(self):
        self.assertEqual(v1._argumentos(["--etapa", "1", "--api", "a", "--saida", "s"]).etapa, 1)

    def test_nao_existe_etapa_do_piloto_completo(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            v1._argumentos(["--etapa", "4", "--api", "a", "--saida", "s", "--orcamento-usd", "1"])

    def test_pasta_da_api_inexistente_da_mensagem_clara_antes_de_ler_a_chave_ou_gastar(self):
        def sem_cliente():
            raise AssertionError("o cliente não deveria ser criado")
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro):
            codigo = v1.main(["--etapa", "1", "--api", "/nao/existe/rest-healing-sut", "--saida", "x"],
                             criar_cliente=sem_cliente)
        self.assertEqual(codigo, 2)
        self.assertIn("A API cobaia não foi encontrada em /nao/existe/rest-healing-sut", erro.getvalue())
        self.assertIn("confira o nome da pasta", erro.getvalue())

    def test_limites_padrao_da_d111_na_linha_de_comando(self):
        a = v1._argumentos(["--etapa", "1", "--api", "a", "--saida", "s"])
        self.assertEqual((a.limite_teste_s, a.limite_caso_s, a.limite_llm_s), (120, 180, 120))
        a = v1._argumentos(["--etapa", "1", "--api", "a", "--saida", "s", "--limite-teste-s", "60",
                            "--limite-caso-s", "90", "--limite-llm-s", "30"])
        self.assertEqual((a.limite_teste_s, a.limite_caso_s, a.limite_llm_s), (60, 90, 30))

    def test_o_limite_da_chamada_chega_ao_sdk(self):
        self.assertEqual(chamada_llm.TIMEOUT_S, 120)
        sdk = chamada_llm.ClienteAnthropic("chave-falsa", timeout_s=30)._sdk
        self.assertEqual(sdk.timeout, 30)

    def test_etapa_3_usa_os_quatro_casos_da_d105(self):
        self.assertEqual(v1.CASOS_DA_ETAPA_3, ("A1-001", "A1-004", "A1-010", "A1-003"))


if __name__ == "__main__":
    unittest.main()
