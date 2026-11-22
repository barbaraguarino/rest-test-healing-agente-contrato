"""O cliente real no laço (T23i): o SDK é trocado por um falso, e nenhum teste chama a API paga."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2

from agente_contrato import cliente_claude as cc
from agente_contrato.agentes import SCHEMA_CLASSIFIER, rodar_agente, rodar_agente_unico
from agente_contrato.laco import rodar_laco
from agente_contrato.prompts import carregar
from agente_contrato.registro_llm import LogDeChamadas, PromptAcimaDoLimite
from agente_contrato.relogio import RelogioCaso
from tests.llm_simulado import FerramentasFalsas
from tests.relogio_falso import RelogioFalso

PEDIDO_HTTP = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def bloco(tipo: str, **campos) -> SimpleNamespace:
    return SimpleNamespace(type=tipo, **campos)


def mensagem(blocos: list, stop_reason: str = "end_turn", entrada: int = 5000, saida: int = 1000,
             thinking: int | None = 200) -> SimpleNamespace:
    """Uma resposta como a do SDK, só com os campos que o cliente lê."""
    detalhes = None if thinking is None else SimpleNamespace(thinking_tokens=thinking)
    return SimpleNamespace(content=blocos, stop_reason=stop_reason, model="claude-haiku-5-5", _request_id="req_1",
                           usage=SimpleNamespace(input_tokens=entrada, output_tokens=saida,
                                                 output_tokens_details=detalhes))


PENSAMENTO = bloco("thinking", thinking="", signature="assinatura-opaca")
PEDE_TESTE = mensagem([PENSAMENTO, bloco("text", text="vou rodar"),
                       bloco("tool_use", id="toolu_1", name="rodar_teste", input={})], "tool_use")
TERMINA = mensagem([bloco("text", text="pronto")])


class SdkFalso:
    """Imita `anthropic.Anthropic().messages.create`: cada item do roteiro é uma resposta, uma exceção
    ou uma função sem argumentos (para o teste agir no meio da chamada)."""

    def __init__(self, *roteiro):
        self.roteiro, self.recebidos = list(roteiro), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.recebidos.append(kw)
        item = self.roteiro.pop(0)
        if callable(item):
            item = item()
        if isinstance(item, Exception):
            raise item
        return item


class Base(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.log = LogDeChamadas(Path(pasta.name, "chamadas.jsonl"))

    def modelo(self, sdk, formato=None) -> cc.ModeloClaude:
        return cc.ModeloClaude(sdk, "sistema", [], "classifier", self.log, "A1-001", 2, "abc123", formato)

    def linhas(self) -> list[dict]:
        if not self.log.caminho.exists():
            return []
        return [json.loads(l) for l in self.log.caminho.read_text(encoding="utf-8").splitlines()]

    def rodar(self, sdk, relogio=None):
        return rodar_laco(self.modelo(sdk), "O teste falhou.", {"rodar_teste": lambda e: "falhou de novo"}, 4, relogio)


class TestNoLaco(Base):
    def test_uma_volta_com_ferramenta_e_o_fim(self):
        sdk = SdkFalso(PEDE_TESTE, TERMINA)
        laco = self.rodar(sdk)
        self.assertEqual((laco.motivo, laco.chamadas, laco.texto_final), ("terminou", 2, "pronto"))
        segunda = sdk.recebidos[1]["messages"]
        self.assertIs(segunda[1]["content"], PEDE_TESTE.content)  # o pensamento volta sem mudança
        self.assertEqual(segunda[2]["content"][0]["tool_use_id"], "toolu_1")

    def test_parametros_enviados_em_cada_chamada(self):  # D61
        sdk = SdkFalso(PEDE_TESTE, TERMINA)
        self.rodar(sdk)
        for enviados in sdk.recebidos:
            self.assertEqual((enviados["model"], enviados["max_tokens"]), ("claude-haiku-5-5", 16000))
            self.assertEqual(enviados["output_config"], {"effort": "medium"})
            for proibido in ("temperature", "top_p", "top_k", "thinking"):
                self.assertNotIn(proibido, enviados)

    def test_formato_vai_quando_o_modelo_o_recebe(self):  # D131
        sdk = SdkFalso(TERMINA)
        self.modelo(sdk, formato={"type": "object"})(["x"])
        self.assertEqual(sdk.recebidos[0]["output_config"]["format"], {"type": "json_schema", "schema": {"type": "object"}})


class TestLog(Base):
    def test_uma_linha_por_chamada_com_custo(self):  # D106, D107
        self.rodar(SdkFalso(PEDE_TESTE, TERMINA))
        linhas = self.linhas()
        self.assertEqual(len(linhas), 2)
        primeira = linhas[0]
        self.assertEqual((primeira["id_caso"], primeira["repeticao"], primeira["etapa"]), ("A1-001", 2, "classifier"))
        self.assertEqual((primeira["stop_reason"], primeira["request_id"], primeira["commit_do_prompt"]),
                         ("tool_use", "req_1", "abc123"))
        self.assertEqual((primeira["input_tokens"], primeira["output_tokens"], primeira["thinking_tokens"]),
                         (5000, 1000, 200))
        self.assertAlmostEqual(primeira["custo_usd"], 0.001, places=10)  # 5000 × 0,10 + 1000 × 0,50, por milhão
        self.assertIsNone(primeira["erro"])
        self.assertIn("rodar_teste", primeira["resposta_bruta"])
        self.assertNotIn("assinatura-opaca", primeira["resposta_bruta"])

    def test_a_linha_e_gravada_na_hora(self):  # antes da chamada seguinte já está no disco
        contagem = []
        def segunda():
            contagem.append(len(self.linhas()))
            return TERMINA
        self.rodar(SdkFalso(PEDE_TESTE, segunda))
        self.assertEqual(contagem, [1])


class TestStopReason(Base):
    def test_cada_stop_reason_que_encerra(self):  # D102, D117c
        casos = {"max_tokens": "max_tokens", "refusal": "saida_invalida",
                 "model_context_window_exceeded": "saida_invalida", "pause_turn": "saida_invalida"}
        for stop_reason, codigo in casos.items():
            with self.subTest(stop_reason=stop_reason):
                self.setUp()
                with self.assertRaises(cc.RespostaInvalida) as erro:
                    self.rodar(SdkFalso(mensagem([bloco("text", text="...")], stop_reason)))
                self.assertEqual(erro.exception.codigo, codigo)
                linha, = self.linhas()
                self.assertEqual(linha["stop_reason"], stop_reason)
                self.assertIsNotNone(linha["erro"])
                self.assertGreater(linha["custo_usd"], 0)  # a resposta veio e foi paga


class TestErrosHttp(Base):
    def test_4xx_para_a_execucao_e_fica_no_log(self):  # D104, D108
        for status in (400, 404, 429):
            with self.subTest(status=status):
                self.setUp()
                resposta = httpx2.Response(status, request=PEDIDO_HTTP)
                with self.assertRaises(cc.ErroFatal):
                    self.rodar(SdkFalso(anthropic.APIStatusError("recusado", response=resposta, body=None)))
                linha, = self.linhas()
                self.assertIn(f"HTTP {status}", linha["erro"])
                self.assertEqual(linha["custo_usd"], 0.0)
                self.assertIsNone(linha["input_tokens"])

    def test_5xx_e_erro_de_rede(self):  # D104: o runner reexecuta o caso
        resposta = httpx2.Response(503, request=PEDIDO_HTTP)
        for excecao in (anthropic.APIStatusError("fora do ar", response=resposta, body=None),
                        anthropic.APIConnectionError(request=PEDIDO_HTTP)):
            with self.subTest(excecao=type(excecao).__name__):
                self.setUp()
                with self.assertRaises(cc.ErroDeRede):
                    self.rodar(SdkFalso(excecao))
                self.assertEqual(len(self.linhas()), 1)

    def test_timeout_no_meio_do_laco_nao_conta_no_relogio_do_caso(self):  # D111(b), ponto 2 do debate
        agora = RelogioFalso()
        relogio = RelogioCaso(agora=agora)
        def demora_e_desiste():
            agora.andar(360)  # 120 s × (1 tentativa + 2 repetições do SDK)
            return anthropic.APITimeoutError(request=PEDIDO_HTTP)
        with self.assertRaises(cc.ErroDeRede):
            self.rodar(SdkFalso(PEDE_TESTE, demora_e_desiste), relogio)
        self.assertEqual(relogio.gasto(), 0)
        self.assertIn("APITimeoutError", self.linhas()[1]["erro"])


class TestLimiteDoPrompt(Base):
    def test_acima_de_100_mil_grava_a_linha_e_para(self):  # D106
        with self.assertRaises(PromptAcimaDoLimite):
            self.rodar(SdkFalso(mensagem([bloco("text", text="x")], entrada=100_001)))
        linha, = self.linhas()
        self.assertIsNone(linha["custo_usd"])
        self.assertEqual(linha["input_tokens"], 100_001)
        self.assertIn("100001", linha["erro"])


class TestFabrica(Base):
    def fabrica(self, sdk) -> cc.FabricaClaude:
        return cc.FabricaClaude(sdk, self.log, "A1-001", 1, "abc123")

    def test_a_etapa_sai_do_prompt_de_sistema(self):
        sdk = SdkFalso(TERMINA, TERMINA)
        fabrica = self.fabrica(sdk)
        fabrica(carregar("classifier"), [])(["x"])
        fabrica(carregar("repair"), [])(["x"])
        self.assertEqual([l["etapa"] for l in self.linhas()], ["classifier", "repair"])

    def test_prompt_desconhecido(self):
        with self.assertRaises(ValueError):
            self.fabrica(SdkFalso())("outro prompt", [])

    def test_os_agentes_gravam_o_tratamento(self):  # T49
        self.fabrica(SdkFalso(TERMINA))(carregar("classifier"), [])(["x"])
        self.assertEqual(self.linhas()[0]["tratamento"], "agentes")

    def test_agente_unico_grava_a_etapa_e_o_tratamento(self):  # T49
        fabrica = cc.FabricaClaude(SdkFalso(TERMINA), self.log, "A1-001", 1, "abc123", tratamento="agente_unico")
        fabrica(carregar("agente_unico"), [])(["x"])
        linha, = self.linhas()
        self.assertEqual((linha["tratamento"], linha["etapa"]), ("agente_unico", "agente_unico"))

    def test_cada_tratamento_so_aceita_os_seus_prompts(self):  # T49
        with self.assertRaises(ValueError):
            self.fabrica(SdkFalso())(carregar("agente_unico"), [])
        unico = cc.FabricaClaude(SdkFalso(), self.log, "A1-001", 1, "abc123", tratamento="agente_unico")
        for etapa in ("classifier", "repair"):
            with self.subTest(etapa=etapa), self.assertRaises(ValueError):
                unico(carregar(etapa), [])

    def test_cada_modelo_tem_a_sua_conversa(self):
        sdk = SdkFalso(TERMINA, TERMINA)
        fabrica = self.fabrica(sdk)
        fabrica(carregar("classifier"), [])(["primeira"])
        fabrica(carregar("repair"), [])(["segunda"])
        self.assertEqual(sdk.recebidos[1]["messages"], [{"role": "user", "content": "segunda"}])


class TestAgenteInteiro(Base):
    """O `rodar_agente` da T23f com a FabricaClaude no lugar do simulado, sem mudar o laço nem os agentes."""

    def test_classifier_e_repair_com_o_cliente_real(self):
        rotulo = '{"rotulo": "legitima", "justificativa": "O campo nome virou titulo."}'
        salva = mensagem([bloco("tool_use", id="toolu_r1", name="salvar_reparo",
                                input={"metodo_reparado": "void lista() {}"})], "tool_use")
        sdk = SdkFalso(mensagem([bloco("text", text=rotulo)]), salva, mensagem([bloco("text", text="Reparei.")]))
        ferramentas = FerramentasFalsas(ver_diferenca="- o campo nome foi renomeado para titulo")
        agente = rodar_agente(cc.FabricaClaude(sdk, self.log, "A1-001", 1, "abc123"), ferramentas.dicionario(),
                              RelogioCaso(agora=RelogioFalso()), "src/test/java/loja/ProdutoTest.java",
                              "ProdutoTest", "lista", None, "@Test\nvoid lista() {}")
        self.assertEqual((agente.motivo, agente.classifier.rotulo, agente.chamadas), ("reparo", "legitima", 3))
        self.assertEqual([l["etapa"] for l in self.linhas()], ["classifier", "repair", "repair"])
        self.assertEqual(sdk.recebidos[0]["output_config"]["format"]["schema"], SCHEMA_CLASSIFIER)  # D131
        self.assertNotIn("format", sdk.recebidos[1]["output_config"])
        self.assertEqual(ferramentas.rodadas, ["ver_diferenca", "salvar_reparo"])


class TestAgenteUnicoComOCliente(Base):
    """O `rodar_agente_unico` com a FabricaClaude no lugar do simulado (T49)."""

    def test_um_laco_com_o_schema_em_todas_as_chamadas(self):  # D67, D131
        rotulo = '{"rotulo": "legitima", "justificativa": "Troquei nome por titulo."}'
        salva = mensagem([bloco("tool_use", id="toolu_r1", name="salvar_reparo",
                                input={"metodo_reparado": "void lista() {}"})], "tool_use")
        sdk = SdkFalso(salva, mensagem([bloco("text", text=rotulo)]))
        ferramentas = FerramentasFalsas()
        r = rodar_agente_unico(cc.FabricaClaude(sdk, self.log, "A1-001", 1, "abc123", tratamento="agente_unico"),
                               ferramentas.dicionario(), RelogioCaso(agora=RelogioFalso()),
                               "src/test/java/loja/ProdutoTest.java", "ProdutoTest", "lista", None,
                               "@Test\nvoid lista() {}")
        self.assertEqual((r.motivo, r.rotulo, r.chamadas), ("reparo", "legitima", 2))
        self.assertEqual([(l["tratamento"], l["etapa"]) for l in self.linhas()], [("agente_unico", "agente_unico")] * 2)
        for enviado in sdk.recebidos:
            self.assertEqual(enviado["output_config"]["format"]["schema"], SCHEMA_CLASSIFIER)
        self.assertEqual([t["name"] for t in sdk.recebidos[0]["tools"]],
                         ["ler_arquivo", "ver_diferenca", "rodar_teste", "salvar_reparo"])


if __name__ == "__main__":
    unittest.main()
