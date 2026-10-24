"""Etapa 4 do runner da v1 (piloto da T10): congelamento dos prompts, aquecimento e retomada.

Sem Maven e sem API: a API cobaia é a de mentira (`api_falsa`) e o modelo é o `ClienteFalso`.
"""

import contextlib
import io
import json
import unittest
from unittest import mock

from agente_contrato import execucao, registro_llm
from agente_contrato import rodar_v1 as v1
from agente_contrato.chamada_llm import ErroFatal
from agente_contrato.registro_llm import LogDeChamadas, Orcamento

from . import api_falsa as af
from .fakes import ClienteFalso, classificacao, reparo
from .test_rodar_v1 import TEXTOS, BaseRodada

CONGELADO, CODIGO = v1.COMMIT_DOS_PROMPTS_DA_T10, "c" * 40
LIMITES = execucao.Limites(llm_s=120)


def _certo():
    return [classificacao("legitima"), reparo(af.metodo_certo())]


class CongelamentoTest(unittest.TestCase):
    def test_so_o_commit_congelado_e_o_codigo_commitado_passam(self):
        self.assertIsNone(v1.conferir_congelamento(CONGELADO, CODIGO))

    def test_outro_commit_de_prompt_nao_roda(self):
        self.assertIn("51894a8", v1.conferir_congelamento("82c4edb" + "0" * 33, CODIGO))

    def test_prompt_com_mudanca_pendente_nao_roda(self):
        self.assertIsNotNone(v1.conferir_congelamento(CONGELADO + "+alterado", CODIGO))

    def test_codigo_com_mudanca_pendente_nao_roda(self):
        self.assertIn("agente_contrato/", v1.conferir_congelamento(CONGELADO, CODIGO + "+alterado"))

    def test_o_commit_congelado_e_o_51894a8(self):
        self.assertTrue(CONGELADO.startswith("51894a8"))


class RodadaDaEtapa4(BaseRodada):
    def rodar4(self, roteiro, repeticoes=3, limite=0.10, retomar=False, rodar=None, oraculo=None):
        anteriores = v1.carregar_anteriores(self.saida, af.TAG, retomar, "abc123", "def456", LIMITES)
        gasto, tokens = registro_llm.gasto_do_log(self.saida / "chamadas.jsonl")
        self.cliente = ClienteFalso(roteiro)
        self.rodar_falso = rodar or af.RodarFalso()
        chamador = v1.Chamador(self.cliente, LogDeChamadas(self.saida / "chamadas.jsonl"),
                               Orcamento(limite, gasto, tokens), TEXTOS, "abc123")
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            codigo = v1.executar_rodada([self.entrada], {"A1-901": oraculo or af.ORACULO_LEGITIMO}, self.api.api,
                                        af.TAG, self.api.raiz_repo, self.saida, repeticoes, chamador,
                                        self.rodar_falso, "def456", LIMITES, anteriores, aquecer_antes=True)
        self.console = out.getvalue()
        return codigo

    def log_v1(self):
        return json.loads((self.saida / "log-v1.json").read_text(encoding="utf-8"))


class AquecimentoTest(RodadaDaEtapa4):
    def test_um_maven_antes_do_primeiro_caso_so_no_log(self):
        self.assertEqual(self.rodar4(_certo(), repeticoes=1), v1.SAIDA_OK)
        self.assertEqual(self.rodar_falso.chamadas, 3)  # aquecimento, inicial e final
        (sessao,) = self.log_v1()["sessoes"]
        self.assertEqual(sessao["aquecimento"], {"teste": f"{af.CLASSE}.{af.METODO}", "passou": False,
                                                 "duracao_maven_s": 1.0, "erro": None})
        self.assertEqual(len(self.registros()), 1)  # o aquecimento não é registro
        self.assertIn("aquecimento do Maven (D111f, fora das métricas)", self.console)

    def test_estouro_no_aquecimento_nao_para_a_rodada(self):
        codigo = self.rodar4(_certo(), repeticoes=1, rodar=af.RodarFalso(duracoes=[500, 1, 1]))
        self.assertEqual(codigo, v1.SAIDA_OK)
        self.assertIn("timeout", self.log_v1()["sessoes"][0]["aquecimento"]["erro"])
        self.assertTrue(self.registros()[0]["passou"])


class RetomadaTest(RodadaDaEtapa4):
    def test_sem_retomar_a_pasta_precisa_estar_vazia(self):
        self.rodar4(_certo(), repeticoes=1)
        with self.assertRaises(v1.RetomadaInvalida):
            v1.carregar_anteriores(self.saida, af.TAG, False, "abc123", "def456", LIMITES)

    def test_retomar_sem_nada_gravado_comeca_do_zero(self):
        a = v1.carregar_anteriores(self.saida, af.TAG, True, "abc123", "def456", LIMITES)
        self.assertEqual((a.feitos(), a.registros, a.chamadas_sem_registro), (set(), [], []))

    def test_parada_por_orcamento_e_retomada_completam_as_tres_repeticoes(self):
        self.assertEqual(self.rodar4(_certo(), limite=0.001), v1.SAIDA_ORCAMENTO)
        self.assertEqual([r["repeticao"] for r in self.registros()], [1])
        gasto, _ = registro_llm.gasto_do_log(self.saida / "chamadas.jsonl")

        self.assertEqual(self.rodar4(_certo() * 2, retomar=True), v1.SAIDA_OK)
        self.assertEqual([r["repeticao"] for r in self.registros()], [1, 2, 3])
        self.assertEqual(len(self.cliente.chamadas), 4)  # nada refeito da repetição 1
        self.assertEqual([x["repeticao"] for x in self.resumo()], [1, 2, 3])
        sessoes = self.log_v1()["sessoes"]
        self.assertEqual([s["execucoes_ja_gravadas"] for s in sessoes], [0, 1])
        self.assertEqual(len(self.linhas_do_log()), 6)
        self.assertGreater(gasto, 0)

    def test_o_orcamento_da_retomada_soma_o_que_ja_foi_gasto(self):
        self.rodar4(_certo(), repeticoes=1)
        ja = registro_llm.gasto_do_log(self.saida / "chamadas.jsonl")[0]
        # o limite cabe numa sessão nova, mas não na rodada inteira: para antes de chamar
        codigo = self.rodar4(_certo(), repeticoes=2, retomar=True, limite=ja)
        self.assertEqual(codigo, v1.SAIDA_ORCAMENTO)
        self.assertEqual(self.cliente.chamadas, [])

    def test_execucao_interrompida_e_refeita_e_as_chamadas_pagas_ficam_no_log(self):
        codigo = self.rodar4(_certo() + [classificacao("legitima"), ErroFatal("HTTP 400", 0.1)])
        self.assertEqual(codigo, v1.SAIDA_ERRO_FATAL)
        a = v1.carregar_anteriores(self.saida, af.TAG, True, "abc123", "def456", LIMITES)
        self.assertEqual(a.chamadas_sem_registro, [{"id_caso": "A1-901", "repeticao": 2, "chamadas": 2}])

        self.assertEqual(self.rodar4(_certo() * 2, retomar=True), v1.SAIDA_OK)
        self.assertEqual([r["repeticao"] for r in self.registros()], [1, 2, 3])
        self.assertEqual(self.log_v1()["sessoes"][1]["chamadas_sem_registro"],
                         [{"id_caso": "A1-901", "repeticao": 2, "chamadas": 2}])
        self.assertEqual(len(self.linhas_do_log()), 8)  # as 2 sem registro continuam lá
        self.assertIn("chamadas pagas sem registro: 2", self.console)

    def test_resultado_sem_linha_no_log_roda_de_novo(self):
        self.rodar4(_certo() * 2, repeticoes=2)
        log = self.log_v1()
        log["execucoes"] = log["execucoes"][:1]  # a queda entre gravar o resultado e gravar o log
        (self.saida / "log-v1.json").write_text(json.dumps(log), encoding="utf-8")
        a = v1.carregar_anteriores(self.saida, af.TAG, True, "abc123", "def456", LIMITES)
        self.assertEqual(([r["repeticao"] for r in a.registros], a.feitos()), ([1], {("A1-901", 1)}))
        self.assertEqual(a.chamadas_sem_registro, [{"id_caso": "A1-901", "repeticao": 2, "chamadas": 2}])

    def test_tudo_gravado_nao_chama_nada(self):
        self.rodar4(_certo() * 3)
        self.assertEqual(self.rodar4([], retomar=True), v1.SAIDA_OK)
        self.assertEqual((self.cliente.chamadas, self.rodar_falso.chamadas), ([], 0))
        self.assertIn("nada a rodar", self.console)
        self.assertEqual(len(self.log_v1()["sessoes"]), 1)

    def test_nao_mistura_prompt_codigo_limites_ou_tag(self):
        self.rodar4(_certo(), repeticoes=1)
        for args in ((af.TAG, True, "outro", "def456", LIMITES), (af.TAG, True, "abc123", "outro", LIMITES),
                     (af.TAG, True, "abc123", "def456", execucao.Limites(caso_s=90, llm_s=120)),
                     ("outra-tag", True, "abc123", "def456", LIMITES)):
            with self.subTest(args=args[:4]), self.assertRaises(v1.RetomadaInvalida):
                v1.carregar_anteriores(self.saida, *args)


class GastoDoLogTest(BaseRodada):
    def test_soma_custo_e_tokens_e_ignora_a_chamada_sem_resposta(self):
        self.assertEqual(registro_llm.gasto_do_log(self.saida / "chamadas.jsonl"), (0.0, 0))
        self.rodar(_certo() + [classificacao("legitima"), ErroFatal("HTTP 400", 0.1)], repeticoes=2)
        gasto, tokens = registro_llm.gasto_do_log(self.saida / "chamadas.jsonl")
        self.assertAlmostEqual(gasto, 3 * registro_llm.custo_usd(registro_llm.Uso(6000, 500, None)), places=10)
        self.assertEqual(tokens, 3 * 6500)


class LinhaDeComandoDaEtapa4Test(BaseRodada):
    def main4(self, *extra, commit=CONGELADO, codigo=CODIGO, resposta="não"):
        criados = []

        def criar():
            criados.append(1)
            return ClienteFalso([])
        argv = ["--etapa", "4", "--api", str(self.api.api), "--saida", str(self.saida), "--orcamento-usd", "0.3",
                *extra]
        with mock.patch.object(v1.prompts, "commit_dos_prompts", return_value=commit), \
                mock.patch.object(v1, "commit_do_codigo", return_value=codigo), \
                mock.patch("builtins.input", return_value=resposta), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            r = v1.main(argv, criar_cliente=criar, rodar=af.RodarFalso())
        return r, out.getvalue(), err.getvalue(), criados

    def test_prompt_fora_do_congelado_para_antes_de_ler_a_chave(self):
        codigo, _, err, criados = self.main4(commit="82c4edb" + "0" * 33)
        self.assertEqual((codigo, criados), (v1.SAIDA_NAO_CONGELADO, []))
        self.assertIn("a etapa 4 não roda", err)

    def test_codigo_alterado_para_antes_de_ler_a_chave(self):
        codigo, _, _, criados = self.main4(codigo=CODIGO + "+alterado")
        self.assertEqual((codigo, criados), (v1.SAIDA_NAO_CONGELADO, []))

    def test_pasta_com_rodada_sem_retomar_para_antes_de_ler_a_chave(self):
        self.saida.mkdir()
        (self.saida / "chamadas.jsonl").write_text("", encoding="utf-8")
        codigo, _, err, criados = self.main4()
        self.assertEqual((codigo, criados), (2, []))
        self.assertIn("--retomar", err)

    def test_os_doze_casos_em_ordem_e_cancelar_nao_gasta(self):
        codigo, out, _, _ = self.main4()
        self.assertEqual(codigo, 1)
        self.assertIn("casos " + ", ".join(f"A1-{i:03d}" for i in range(1, 13)) + " |", out)
        self.assertIn("cancelado, nada foi gasto", out)
        self.assertFalse((self.saida / "chamadas.jsonl").exists())

    def test_retomar_mostra_o_que_ja_foi_gasto(self):
        self.saida.mkdir()
        linha = {c: None for c in registro_llm.CAMPOS_DO_LOG}
        linha.update(id_caso="A1-001", repeticao=1, etapa="classifier", custo_usd=0.0012, input_tokens=10,
                     output_tokens=2)
        (self.saida / "chamadas.jsonl").write_text(json.dumps(linha) + "\n", encoding="utf-8")
        _, out, _, _ = self.main4("--retomar")
        self.assertIn("já gastos US$ 0.001200 nesta pasta", out)


if __name__ == "__main__":
    unittest.main()
