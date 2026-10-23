import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato import registro_llm as r


class CustoTest(unittest.TestCase):
    def test_exemplos_da_aula(self):
        self.assertAlmostEqual(r.custo_usd(r.Uso(6000, 500, None)), 0.00085, places=10)
        self.assertAlmostEqual(r.custo_usd(r.Uso(7000, 1500, None)), 0.00145, places=10)
        self.assertAlmostEqual(r.custo_usd(r.Uso(8000, 1000, None)), 0.0013, places=10)

    def test_zero_tokens_custa_zero(self):
        self.assertEqual(r.custo_usd(r.Uso(0, 0, None)), 0.0)

    def test_reproduz_o_pior_caso_da_d105(self):
        # 7 chamadas, 10 mil tokens de entrada e 16 mil de saída cada uma: cerca de US$ 0,063
        um = r.custo_usd(r.Uso(10_000, 16_000, None))
        self.assertAlmostEqual(um, 0.009, places=10)
        self.assertAlmostEqual(7 * um, 0.063, places=10)

    def test_limite_de_100_mil_tokens_de_entrada(self):
        r.custo_usd(r.Uso(100_000, 1, None))  # o limite em si ainda vale
        with self.assertRaises(r.PromptAcimaDoLimite):
            r.custo_usd(r.Uso(100_001, 1, None))

    def test_tokens_negativos(self):
        with self.assertRaises(ValueError):
            r.custo_usd(r.Uso(-1, 0, None))

    def test_o_preco_guarda_a_fonte_e_a_data(self):
        self.assertIn("pricing", r.PRECO_HAIKU_5_5.fonte)
        self.assertEqual(r.PRECO_HAIKU_5_5.consultado_em, "2026-10-22")

    def test_thinking_nao_entra_na_soma_porque_ja_esta_na_saida(self):
        com = r.custo_usd(r.Uso(1000, 500, 300))
        sem = r.custo_usd(r.Uso(1000, 500, None))
        self.assertEqual(com, sem)


class OrcamentoTest(unittest.TestCase):
    def test_acumula_gasto_e_tokens(self):
        o = r.Orcamento(0.10)
        o.somar(r.Uso(1000, 200, None), 0.0002)
        o.somar(r.Uso(500, 100, None), 0.0001)
        self.assertAlmostEqual(o.gasto_usd, 0.0003)
        self.assertEqual(o.tokens, 1800)

    def test_verificar_passa_abaixo_do_limite_e_para_ao_chegar(self):
        o = r.Orcamento(0.01)
        o.somar(r.Uso(0, 0, None), 0.0099)
        o.verificar()
        o.somar(r.Uso(0, 0, None), 0.0001)
        with self.assertRaises(r.OrcamentoEsgotado) as ctx:
            o.verificar()
        self.assertEqual(ctx.exception.limite, 0.01)

    def test_limite_invalido(self):
        for v in (0, -1):
            with self.assertRaises(ValueError):
                r.Orcamento(v)


def _campos(**extra):
    base = dict(id_caso="A1-001", repeticao=1, etapa="classifier", modelo_retornado="claude-haiku-5-5",
                stop_reason="end_turn", input_tokens=10, output_tokens=5, thinking_tokens=None,
                custo_usd=0.0001, request_id="req_1", latencia_s=1.5, commit_do_prompt="abc",
                resposta_bruta='{"rotulo":"legitima"}', erro=None)
    base.update(extra)
    return base


class LogTest(unittest.TestCase):
    def _log(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return r.LogDeChamadas(Path(tmp.name, "sub", "chamadas.jsonl"))

    def test_cada_chamada_vira_uma_linha_legivel_na_hora(self):
        log = self._log()
        log.registrar(**_campos())
        log.registrar(**_campos(etapa="repair", resposta_bruta="método com acentuação"))
        linhas = log.caminho.read_text(encoding="utf-8").splitlines()  # sem fechar nada antes
        self.assertEqual(len(linhas), 2)
        self.assertEqual(json.loads(linhas[0])["etapa"], "classifier")
        self.assertIn("acentuação", linhas[1])  # sem escapar o Unicode

    def test_so_aceita_exatamente_os_campos_da_d106(self):
        log = self._log()
        with self.assertRaises(ValueError):
            log.registrar(**{k: v for k, v in _campos().items() if k != "request_id"})
        with self.assertRaises(ValueError):
            log.registrar(**_campos(extra=1))
        self.assertFalse(log.caminho.exists())

    def test_etapa_invalida(self):
        with self.assertRaises(ValueError):
            self._log().registrar(**_campos(etapa="planner"))

    def test_chamada_com_erro_de_rede_pode_ter_campos_nulos(self):
        log = self._log()
        log.registrar(**_campos(stop_reason=None, input_tokens=None, output_tokens=None, request_id=None,
                                resposta_bruta=None, custo_usd=0.0, erro="timeout de 120 s"))
        self.assertIsNone(json.loads(log.caminho.read_text())["stop_reason"])


if __name__ == "__main__":
    unittest.main()
