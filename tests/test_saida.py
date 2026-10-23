import json
import unittest

from agente_contrato import resultados, saida

ORIGINAL = '''class T {
    @Test
    @Sql({"/fixtures/a.sql"})
    void alvo() throws Exception {
        verificaA();
    }

    @Test
    void outro() { verificaB(); }
}
'''

REPARADO = '''@Test
@Sql({"/fixtures/OUTRA.sql"})
void alvo() throws Exception {
    verificaNovo();
}'''


def _json(**campos) -> str:
    return json.dumps(campos)


class CodigosTest(unittest.TestCase):
    def test_codigos_e_rotulos_sao_valores_validos_da_d74(self):
        self.assertIn(saida.SAIDA_INVALIDA, resultados._VALORES["erro"])
        self.assertIn(saida.MAX_TOKENS, resultados._VALORES["erro"])
        self.assertEqual(set(saida.ROTULOS), resultados._VALORES["rotulo_oraculo"])

    def test_schemas_fecham_o_objeto_e_listam_o_enum(self):
        for s in (saida.SCHEMA_CLASSIFIER, saida.SCHEMA_REPAIR):
            self.assertIs(s["additionalProperties"], False)
            self.assertEqual(set(s["required"]), set(s["properties"]))
        self.assertEqual(saida.SCHEMA_CLASSIFIER["properties"]["rotulo"]["enum"], list(saida.ROTULOS))


class ParadaTest(unittest.TestCase):
    def _codigo(self, stop_reason, texto='{"rotulo":"legitima","justificativa":"x"}'):
        with self.assertRaises(saida.SaidaRejeitada) as ctx:
            saida.ler_classificacao(stop_reason, texto)
        return ctx.exception.codigo

    def test_max_tokens_vence_o_json_cortado(self):
        self.assertEqual(self._codigo("max_tokens", '{"rotulo": "legit'), saida.MAX_TOKENS)

    def test_max_tokens_mesmo_com_json_completo(self):
        self.assertEqual(self._codigo("max_tokens"), saida.MAX_TOKENS)

    def test_refusal_e_estouro_de_contexto_sao_saida_invalida(self):
        self.assertEqual(self._codigo("refusal", ""), saida.SAIDA_INVALIDA)
        self.assertEqual(self._codigo("model_context_window_exceeded", None), saida.SAIDA_INVALIDA)

    def test_parada_inesperada_ou_ausente_e_saida_invalida(self):
        self.assertEqual(self._codigo("tool_use"), saida.SAIDA_INVALIDA)
        self.assertEqual(self._codigo(None), saida.SAIDA_INVALIDA)


class ClassificacaoTest(unittest.TestCase):
    def _invalida(self, texto):
        with self.assertRaises(saida.SaidaRejeitada) as ctx:
            saida.ler_classificacao("end_turn", texto)
        self.assertEqual(ctx.exception.codigo, saida.SAIDA_INVALIDA)

    def test_resposta_valida(self):
        c = saida.ler_classificacao("end_turn", _json(rotulo="problema_real", justificativa=" Falta o campo. "))
        self.assertEqual(c, saida.Classificacao("problema_real", "Falta o campo."))

    def test_rotulo_nao_diferencia_maiusculas(self):
        self.assertEqual(saida.ler_classificacao("end_turn", _json(rotulo="LEGITIMA", justificativa="x")).rotulo,
                         saida.LEGITIMA)

    def test_rotulo_fora_do_enum(self):
        self._invalida(_json(rotulo="legítima", justificativa="x"))
        self._invalida(_json(rotulo="talvez", justificativa="x"))

    def test_json_ilegivel_ou_de_outro_tipo(self):
        self._invalida("não é json")
        self._invalida("[1, 2]")
        self._invalida("")

    def test_campo_faltando_ou_sobrando(self):
        self._invalida(_json(rotulo="legitima"))
        self._invalida(_json(rotulo="legitima", justificativa="x", extra=1))

    def test_tipos_errados(self):
        self._invalida(_json(rotulo=1, justificativa="x"))
        self._invalida(_json(rotulo="legitima", justificativa=None))

    def test_justificativa_vazia_nao_invalida_a_resposta(self):
        # a D102 não lista justificativa vazia como saída inválida
        self.assertEqual(saida.ler_classificacao("end_turn", _json(rotulo="legitima", justificativa="")).rotulo,
                         saida.LEGITIMA)


class ReparoTest(unittest.TestCase):
    def test_resposta_valida(self):
        self.assertEqual(saida.ler_reparo("end_turn", _json(metodo_reparado="void x() {}")), "void x() {}")

    def test_vazio_ou_so_espacos(self):
        for texto in ("", "  \n "):
            with self.assertRaises(saida.SaidaRejeitada):
                saida.ler_reparo("end_turn", _json(metodo_reparado=texto))

    def test_max_tokens_no_repair(self):
        with self.assertRaises(saida.SaidaRejeitada) as ctx:
            saida.ler_reparo("max_tokens", '{"metodo_reparado": "void x() {')
        self.assertEqual(ctx.exception.codigo, saida.MAX_TOKENS)


class EncaixarTest(unittest.TestCase):
    def test_troca_so_o_corpo_e_mantem_anotacoes_e_assinatura_do_original(self):
        novo = saida.encaixar(ORIGINAL, "alvo", REPARADO)
        self.assertIn("verificaNovo();", novo)
        self.assertNotIn("verificaA();", novo)
        self.assertIn('@Sql({"/fixtures/a.sql"})', novo)   # anotação do original
        self.assertNotIn("OUTRA.sql", novo)                # a do modelo é descartada
        self.assertIn("void outro() { verificaB(); }", novo)

    def test_aceita_o_metodo_dentro_de_cerca_de_markdown(self):
        novo = saida.encaixar(ORIGINAL, "alvo", f"```java\n{REPARADO}\n```")
        self.assertIn("verificaNovo();", novo)

    def test_metodo_com_outro_nome_nao_encaixa(self):
        with self.assertRaises(saida.SaidaRejeitada) as ctx:
            saida.encaixar(ORIGINAL, "alvo", "void outroNome() { }")
        self.assertEqual(ctx.exception.codigo, saida.SAIDA_INVALIDA)

    def test_chaves_desbalanceadas_nao_encaixam(self):
        with self.assertRaises(saida.SaidaRejeitada):
            saida.encaixar(ORIGINAL, "alvo", "void alvo() { if (x) { }")

    def test_chave_dentro_de_texto_nao_conta(self):
        reparado = 'void alvo() { texto("}"); }'
        self.assertIn('texto("}");', saida.encaixar(ORIGINAL, "alvo", reparado))


if __name__ == "__main__":
    unittest.main()
