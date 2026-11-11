"""Testes do cliente real do Claude (T23i). Nenhum teste chama a API paga: o SDK é trocado por um falso."""
import unittest

from agente_contrato.cliente_claude import parametros

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


if __name__ == "__main__":
    unittest.main()
