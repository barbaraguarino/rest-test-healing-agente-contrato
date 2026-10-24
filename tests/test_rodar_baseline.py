import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato import baseline as b
from agente_contrato import execucao as ex
from agente_contrato import resultados
from agente_contrato import rodar_baseline as rb

from . import api_falsa as af
from .fakes import RelogioFalso

ORIGINAL = '''class T {
    void teste() throws Exception {
        mockMvc.perform(post("/pedidos")
                        .content("""
                                {"a": 1, "nome": "x"}
                                """))
                .andExpect(status().isCreated());
    }
}
'''
REPARADO = ORIGINAL.replace('"nome"', '"titulo"')
ORACULO = {"id_caso": "A1-999", "categoria": "renomeacao", "rotulo_oraculo": "legitima",
           "correcao_esperada": "casos/esperado.patch"}


def execucao(**kw):
    from agente_contrato import contrato as c
    p = c.Propriedade("string", None, None, False)
    base = dict(id_caso="A1-999", classe="T", metodo="teste", decisao=b.REPARAR, compilou=True,
                passou=True, erro=None, tempo_s=0.0123456, original=ORIGINAL, reparado=REPARADO,
                arquivo_relativo="src/test/java/T.java",
                mudancas=[c.Mudanca(c.RENOMEACAO, "POST", "/pedidos", c.REQUISICAO, "nome", "titulo", p, p)],
                rotas={"POST": {"/pedidos"}})
    base.update(kw)
    return rb.Execucao(**base)


class RegistrarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        (self.raiz / "casos").mkdir()
        alvo = self.raiz / "src/test/java/T.java"
        alvo.parent.mkdir(parents=True)
        alvo.write_text(ORIGINAL)
        patch = ("--- a/src/test/java/T.java\n+++ b/src/test/java/T.java\n@@ -3,5 +3,5 @@\n"
                 '         mockMvc.perform(post("/pedidos")\n'
                 '                         .content("""\n'
                 '-                                {"a": 1, "nome": "x"}\n'
                 '+                                {"a": 1, "titulo": "x"}\n'
                 '                                 """))\n'
                 '                 .andExpect(status().isCreated());\n')
        (self.raiz / "casos/esperado.patch").write_text(patch)

    def test_equivalente_com_troca_de_cenario_vai_para_revisao_manual(self):
        from unittest import mock
        from agente_contrato import comparador
        contraditorio = comparador.Comparacao(True, True, ())
        with mock.patch.object(rb.comparador, "comparar", return_value=contraditorio):
            registro, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertTrue(extras["revisao_manual"])
        self.assertIn("inconsistência", " ".join(extras["motivos"]))
        self.assertIsNone(registro["equivalente_oraculo"])  # pendente, no próprio arquivo de resultados
        self.assertEqual(resultados.problemas(registro), [])

    def test_reparo_coerente_nao_vai_para_revisao_manual(self):
        _, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertFalse(extras["revisao_manual"])

    def test_registro_de_reparo_equivalente_e_valido_na_d74(self):
        registro, extras = rb.registrar(execucao(), ORACULO, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertEqual((registro["decisao"], registro["equivalente_oraculo"],
                          registro["cenario_alterado"], registro["assercoes_enfraquecidas"]),
                         ("reparar", True, False, False))
        self.assertEqual(registro["tempo_s"], 0.0123)
        self.assertFalse(extras["revisao_manual"])

    def test_oraculo_so_entra_no_registro(self):
        registro, _ = rb.registrar(execucao(), ORACULO, 2, self.raiz)
        self.assertEqual((registro["categoria"], registro["rotulo_oraculo"], registro["repeticao"]),
                         ("renomeacao", "legitima", 2))

    def test_nao_reparar_deixa_os_campos_de_reparo_nulos(self):
        e = execucao(decisao=b.NAO_REPARAR, compilou=None, passou=False, reparado=None)
        registro, extras = rb.registrar(e, ORACULO, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertEqual([registro[c] for c in ("compilou", "equivalente_oraculo",
                                                "assercoes_enfraquecidas", "cenario_alterado")], [None] * 4)
        self.assertFalse(extras["revisao_manual"])

    def test_regressao_reparada_tem_equivalente_nulo_e_sem_revisao_manual(self):
        oraculo = {**ORACULO, "rotulo_oraculo": "problema_real", "correcao_esperada": None}
        registro, extras = rb.registrar(execucao(passou=False), oraculo, 1, self.raiz)
        self.assertEqual(resultados.problemas(registro), [])
        self.assertIsNone(registro["equivalente_oraculo"])
        self.assertFalse(extras["revisao_manual"])

    def test_reparo_que_passa_mas_a_regra_reprova_vai_para_revisao_manual(self):
        outro = REPARADO.replace('"a": 1', '"a": 2')  # valor diferente da correção esperada
        registro, extras = rb.registrar(execucao(reparado=outro), ORACULO, 1, self.raiz)
        self.assertTrue(extras["revisao_manual"])
        self.assertIsNone(registro["equivalente_oraculo"])

    def test_erro_de_guarda_fica_registrado(self):
        e = execucao(decisao=b.NAO_REPARAR, compilou=None, passou=False, reparado=None, erro="guarda")
        registro, _ = rb.registrar(e, ORACULO, 1, self.raiz)
        self.assertEqual((registro["decisao"], registro["erro"]), ("nao_reparar", "guarda"))
        self.assertEqual(resultados.problemas(registro), [])

    def test_assinatura_ignora_tempo_e_repeticao_mas_nao_o_conteudo(self):
        r1, _ = rb.registrar(execucao(tempo_s=1.0), ORACULO, 1, self.raiz)
        r2, _ = rb.registrar(execucao(tempo_s=9.0), ORACULO, 2, self.raiz)
        self.assertEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r2, REPARADO))
        self.assertNotEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r1, REPARADO + " "))
        r3, _ = rb.registrar(execucao(passou=False), ORACULO, 3, self.raiz)
        self.assertNotEqual(rb.assinatura(r1, REPARADO), rb.assinatura(r3, REPARADO))


class LimitesDeTempoTest(unittest.TestCase):
    """D111 na baseline, com a API de mentira e o Maven simulado (sem processo)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        pasta = Path(self._tmp.name)
        self.api = af.criar(pasta)
        self.entrada = rb.Entrada("A1-901", self.api.patch, af.CLASSE, af.METODO)
        self.saida = pasta / "saida"

    def rodar(self, duracoes, repeticoes=1, oraculo=None):
        relogio = RelogioFalso()
        self.rodar_falso = af.RodarFalso(duracoes=duracoes, relogio=relogio)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rb.executar_rodada([self.entrada], {"A1-901": oraculo or af.ORACULO_LEGITIMO}, self.api.api, af.TAG,
                               self.api.raiz_repo, self.saida, repeticoes, self.rodar_falso,
                               ex.Limites(relogio=relogio))
        self.console = out.getvalue()
        registros = json.loads((self.saida / "resultados-agente1.json").read_text(encoding="utf-8"))["execucoes"]
        for r in registros:
            self.assertEqual(resultados.problemas(r), [])
        return registros, json.loads((self.saida / "log-baseline.json").read_text(encoding="utf-8"))

    def test_sem_estouro_o_reparo_passa_e_o_log_tem_os_limites(self):
        (r,), log = self.rodar([10, 10])
        self.assertEqual((r["decisao"], r["passou"], r["erro"]), ("reparar", True, None))
        self.assertEqual(log["limites"], {"teste_s": 120, "caso_s": 180, "llm_s": None})
        self.assertEqual((log["execucoes"][0]["duracao_caso_s"], log["execucoes"][0]["estouro"]), (10, None))

    def test_estouro_do_teste_final_e_falha_do_tratamento(self):
        (r,), log = self.rodar([10, 500], oraculo=af.ORACULO_REGRESSAO)
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"]), ("reparar", False, False, "timeout"))
        self.assertEqual(log["execucoes"][0]["estouro"], "teste_final")
        self.assertEqual(self.rodar_falso.chamadas, 2)

    def test_estouro_do_maven_inicial_reexecuta_e_depois_exclui(self):
        (r1, r2), log = self.rodar([500, 10, 10, 500, 500], repeticoes=2)
        self.assertEqual((r1["erro"], r1["passou"]), (None, True))
        self.assertEqual(log["execucoes"][0]["tentativas_maven_inicial"], 2)
        self.assertEqual(r2["erro"], "erro_execucao")
        self.assertEqual(log["exclusoes"], [{"id_caso": "A1-901", "repeticao": 2, "erro": "erro_execucao",
                                             "causa": "estouro_maven_inicial"}])
        self.assertEqual(log["exclusoes_por_causa"], {"estouro_maven_inicial": 1})
        self.assertIn("exclusões (fora das métricas): 1 (estouro_maven_inicial: 1)", self.console)

    def test_teste_que_ja_passa_e_exclusao_com_causa_propria(self):
        relogio = RelogioFalso()
        with contextlib.redirect_stdout(io.StringIO()):
            rb.executar_rodada([self.entrada], {"A1-901": af.ORACULO_LEGITIMO}, self.api.api, af.TAG,
                               self.api.raiz_repo, self.saida, 1, af.RodarFalso(ja_passa=True, relogio=relogio),
                               ex.Limites(relogio=relogio))
        log = json.loads((self.saida / "log-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(log["exclusoes_por_causa"], {"teste_passa_sem_reparo": 1})


if __name__ == "__main__":
    unittest.main()
