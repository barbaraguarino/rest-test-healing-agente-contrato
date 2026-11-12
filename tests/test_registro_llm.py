"""Custo e log das chamadas (T23i, D106, D107): os testes da v1, sem o orçamento, mais o `uso_da_resposta`."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agente_contrato import registro_llm as r


class TestCusto(unittest.TestCase):
    def test_exemplos(self):
        self.assertAlmostEqual(r.custo_usd(r.Uso(6000, 500, None)), 0.00085, places=10)
        self.assertAlmostEqual(r.custo_usd(r.Uso(5000, 1000, None)), 0.001, places=10)

    def test_zero_tokens_custa_zero(self):
        self.assertEqual(r.custo_usd(r.Uso(0, 0, None)), 0.0)

    def test_pior_caso_de_saida_por_chamada(self):  # D61: 16 mil tokens de saída custam US$ 0,008
        self.assertAlmostEqual(r.custo_usd(r.Uso(0, 16_000, None)), 0.008, places=10)

    def test_limite_de_100_mil_tokens_de_entrada(self):  # D106
        r.custo_usd(r.Uso(100_000, 1, None))  # o limite em si ainda vale
        with self.assertRaises(r.PromptAcimaDoLimite):
            r.custo_usd(r.Uso(100_001, 1, None))

    def test_tokens_negativos(self):
        with self.assertRaises(ValueError):
            r.custo_usd(r.Uso(-1, 0, None))

    def test_o_preco_guarda_a_fonte_e_a_data(self):
        self.assertIn("pricing", r.PRECO_HAIKU_5_5.fonte)
        self.assertEqual(r.PRECO_HAIKU_5_5.consultado_em, "2026-10-22")

    def test_thinking_nao_entra_na_soma_porque_ja_esta_na_saida(self):  # D107
        self.assertEqual(r.custo_usd(r.Uso(1000, 500, 300)), r.custo_usd(r.Uso(1000, 500, None)))


class TestUsoDaResposta(unittest.TestCase):
    def test_com_thinking_tokens(self):
        usage = SimpleNamespace(input_tokens=6000, output_tokens=700,
                                output_tokens_details=SimpleNamespace(thinking_tokens=300))
        self.assertEqual(r.uso_da_resposta(usage), r.Uso(6000, 700, 300))

    def test_sem_detalhes_o_thinking_fica_nulo(self):
        self.assertEqual(r.uso_da_resposta(SimpleNamespace(input_tokens=1, output_tokens=2)), r.Uso(1, 2, None))


def campos(**extra) -> dict:
    base = dict(id_caso="A1-001", repeticao=1, etapa="classifier", modelo_retornado="claude-haiku-5-5",
                stop_reason="end_turn", input_tokens=10, output_tokens=5, thinking_tokens=None,
                custo_usd=0.0001, request_id="req_1", latencia_s=1.5, commit_do_prompt="abc",
                resposta_bruta='{"rotulo":"legitima"}', erro=None)
    base.update(extra)
    return base


class TestLog(unittest.TestCase):
    def log(self) -> r.LogDeChamadas:
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        return r.LogDeChamadas(Path(pasta.name, "sub", "chamadas.jsonl"))

    def test_cada_chamada_vira_uma_linha_legivel_na_hora(self):
        log = self.log()
        log.registrar(**campos())
        log.registrar(**campos(etapa="repair", resposta_bruta="método com acentuação"))
        linhas = log.caminho.read_text(encoding="utf-8").splitlines()  # sem fechar nada antes
        self.assertEqual(len(linhas), 2)
        self.assertEqual(json.loads(linhas[0])["etapa"], "classifier")
        self.assertIn("acentuação", linhas[1])

    def test_so_aceita_exatamente_os_campos_da_d106_e_da_d107(self):
        log = self.log()
        with self.assertRaises(ValueError):
            log.registrar(**{k: v for k, v in campos().items() if k != "request_id"})
        with self.assertRaises(ValueError):
            log.registrar(**campos(extra=1))
        self.assertFalse(log.caminho.exists())

    def test_etapa_invalida(self):
        with self.assertRaises(ValueError):
            self.log().registrar(**campos(etapa="planner"))

    def test_chamada_com_erro_pode_ter_campos_nulos(self):
        log = self.log()
        log.registrar(**campos(stop_reason=None, input_tokens=None, output_tokens=None, request_id=None,
                               resposta_bruta=None, custo_usd=0.0, erro="APITimeoutError"))
        self.assertIsNone(json.loads(log.caminho.read_text(encoding="utf-8"))["stop_reason"])


if __name__ == "__main__":
    unittest.main()
