"""Testes do cliente real do Claude (T23i). Nenhum teste chama a API paga: o SDK é trocado por um falso."""
import unittest
from types import SimpleNamespace

from agente_contrato.cliente_claude import mensagens, para_resposta, parametros
from agente_contrato.laco import PedidoFerramenta, RespostaModelo, ResultadoFerramenta


def bloco(tipo: str, **campos) -> SimpleNamespace:
    """Um bloco de `content` como o SDK devolve (objeto com `.type` e os outros campos)."""
    return SimpleNamespace(type=tipo, **campos)


PENSAMENTO = bloco("thinking", thinking="", signature="assinatura-opaca")
TEXTO = bloco("text", text="vou rodar o teste")
PEDIDO = bloco("tool_use", id="toolu_1", name="rodar_teste", input={})

SCHEMA = {"type": "object", "properties": {"rotulo": {"type": "string"}}, "required": ["rotulo"],
          "additionalProperties": False}
FERRAMENTA = {"name": "rodar_teste", "description": "Roda o teste.", "input_schema": {"type": "object"}}
MENSAGENS = [{"role": "user", "content": "O teste falhou."}]


class TestParametros(unittest.TestCase):
    def test_parametros_da_d61(self):
        enviados = parametros("sistema", [FERRAMENTA], MENSAGENS)
        self.assertEqual(enviados["model"], "claude-haiku-5-5")
        self.assertEqual(enviados["max_tokens"], 16000)
        self.assertEqual(enviados["output_config"], {"effort": "medium"})
        self.assertEqual(enviados["system"], "sistema")
        self.assertEqual(enviados["tools"], [FERRAMENTA])
        self.assertEqual(enviados["messages"], MENSAGENS)

    def test_sem_amostragem_e_sem_thinking(self):
        enviados = parametros("sistema", [FERRAMENTA], MENSAGENS, SCHEMA)
        for proibido in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(proibido, enviados)

    def test_formato_so_quando_pedido(self):  # D131: só o Classifier envia o schema
        enviados = parametros("sistema", [FERRAMENTA], MENSAGENS, SCHEMA)
        self.assertEqual(enviados["output_config"],
                         {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})


class TestParaResposta(unittest.TestCase):
    def test_pedido_de_ferramenta(self):
        resposta = para_resposta([PENSAMENTO, TEXTO, PEDIDO])
        self.assertEqual(resposta, RespostaModelo("vou rodar o teste",
                                                  (PedidoFerramenta("toolu_1", "rodar_teste", {}),)))
        self.assertFalse(resposta.terminou)

    def test_resposta_final_sem_pedidos(self):
        resposta = para_resposta([PENSAMENTO, bloco("text", text='{"rotulo": '), bloco("text", text='"legitima"}')])
        self.assertEqual(resposta.texto, '{"rotulo": "legitima"}')  # os blocos de texto são juntados
        self.assertTrue(resposta.terminou)


class TestMensagens(unittest.TestCase):
    def test_conversa_com_uma_volta(self):
        primeira = [PENSAMENTO, TEXTO, PEDIDO]
        historico = ["O teste falhou.", para_resposta(primeira),
                     (ResultadoFerramenta("toolu_1", "O teste falhou de novo."),)]
        self.assertEqual(mensagens(historico, [primeira]), [
            {"role": "user", "content": "O teste falhou."},
            {"role": "assistant", "content": primeira},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": "O teste falhou de novo.", "is_error": False}]},
        ])

    def test_resposta_do_modelo_volta_sem_mudanca(self):  # o bloco de pensamento é o mesmo objeto
        primeira = [PENSAMENTO, TEXTO, PEDIDO]
        enviadas = mensagens(["O teste falhou.", para_resposta(primeira)], [primeira])
        self.assertIs(enviadas[1]["content"], primeira)
        self.assertIs(enviadas[1]["content"][0], PENSAMENTO)

    def test_erro_de_ferramenta_volta_como_is_error(self):  # D124
        historico = ["x", para_resposta([PEDIDO]), (ResultadoFerramenta("toolu_1", "caminho fora", erro=True),)]
        resultado = mensagens(historico, [[PEDIDO]])[2]["content"][0]
        self.assertTrue(resultado["is_error"])
        self.assertEqual(resultado["content"], "caminho fora")

    def test_varios_pedidos_numa_resposta_voltam_numa_so_mensagem(self):
        dois = [bloco("tool_use", id="a", name="ler_arquivo", input={"caminho": "src"}),
                bloco("tool_use", id="b", name="rodar_teste", input={})]
        historico = ["x", para_resposta(dois), (ResultadoFerramenta("a", "A.java"), ResultadoFerramenta("b", "ok"))]
        enviadas = mensagens(historico, [dois])
        self.assertEqual(len(enviadas), 3)
        self.assertEqual([r["tool_use_id"] for r in enviadas[2]["content"]], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
