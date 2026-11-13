"""Trava de orçamento e soma do log (T23j, D105, D106): da v1, lendo o `chamadas.jsonl`."""
import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato import registro_llm as r


def linha(id_caso: str, repeticao: int, custo, entrada, saida) -> str:
    return json.dumps({"id_caso": id_caso, "repeticao": repeticao, "custo_usd": custo,
                       "input_tokens": entrada, "output_tokens": saida}) + "\n"


class TestGastoDoLog(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.log = Path(self.pasta.name) / "chamadas.jsonl"

    def tearDown(self):
        self.pasta.cleanup()

    def test_sem_arquivo_e_zero(self):
        self.assertEqual(r.gasto_do_log(self.log), (0.0, 0))

    def test_soma_a_rodada_inteira(self):
        self.log.write_text(linha("A1-001", 1, 0.001, 5000, 1000) + linha("A1-002", 1, 0.0005, 3000, 400)
                            + "\n", encoding="utf-8")
        gasto, tokens = r.gasto_do_log(self.log)
        self.assertAlmostEqual(gasto, 0.0015, places=10)
        self.assertEqual(tokens, 9400)

    def test_chamada_sem_resposta_custa_zero(self):  # ErroDeRede: custo 0 e tokens nulos
        self.log.write_text(linha("A1-001", 1, 0.0, None, None), encoding="utf-8")
        self.assertEqual(r.gasto_do_log(self.log), (0.0, 0))

    def test_soma_so_a_execucao_pedida_com_a_reexecucao(self):  # D74, D104
        self.log.write_text(linha("A1-001", 1, 0.001, 5000, 1000) + linha("A1-001", 1, 0.002, 6000, 2000)
                            + linha("A1-001", 2, 0.5, 1, 1) + linha("A1-002", 1, 0.5, 1, 1), encoding="utf-8")
        gasto, tokens = r.gasto_do_log(self.log, "A1-001", 1)
        self.assertAlmostEqual(gasto, 0.003, places=10)
        self.assertEqual(tokens, 14000)


class TestOrcamento(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.log = Path(self.pasta.name) / "chamadas.jsonl"

    def tearDown(self):
        self.pasta.cleanup()

    def test_limite_precisa_ser_positivo(self):
        with self.assertRaises(ValueError):
            r.Orcamento(0, self.log)

    def test_abaixo_do_limite_deixa_chamar(self):
        self.log.write_text(linha("A1-001", 1, 0.04, 1, 1), encoding="utf-8")
        r.Orcamento(0.05, self.log).verificar()

    def test_no_limite_para(self):  # conferido antes de gastar: chegar ao limite já para
        self.log.write_text(linha("A1-001", 1, 0.03, 1, 1) + linha("A1-002", 1, 0.02, 1, 1), encoding="utf-8")
        with self.assertRaises(r.OrcamentoEsgotado) as ctx:
            r.Orcamento(0.05, self.log).verificar()
        self.assertAlmostEqual(ctx.exception.gasto, 0.05, places=10)

    def test_le_o_log_a_cada_conferencia(self):  # a chamada gravada agora conta na próxima conferência
        orcamento = r.Orcamento(0.05, self.log)
        orcamento.verificar()
        self.log.write_text(linha("A1-001", 1, 0.06, 1, 1), encoding="utf-8")
        with self.assertRaises(r.OrcamentoEsgotado):
            orcamento.verificar()


if __name__ == "__main__":
    unittest.main()
