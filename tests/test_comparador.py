import unittest

from agente_contrato import comparador as cp
from agente_contrato import contrato as c

ROTAS = {"POST": {"/pedidos"}}


def java(corpo, status="isCreated()", asserts='.andExpect(jsonPath("$.id").value(is(1)))', sql="/a.sql",
         outro="void outro() {}"):
    return f'''class T {{
    @Sql("{sql}")
    void teste() throws Exception {{
        mockMvc.perform(post("/pedidos")
                        .content("""
                                {corpo}
                                """))
                .andExpect(status().{status})
                {asserts};
    }}

    {outro}
}}
'''


def nova(caminho, tipo="string", enum=None):
    return c.Mudanca(c.CAMPO_OBRIGATORIO_NOVO, "POST", "/pedidos", c.REQUISICAO, caminho,
                     depois=c.Propriedade(tipo, None, tuple(enum) if enum else None, True))


def renomeia(a, b, lado=c.REQUISICAO):
    p = c.Propriedade("string", None, None, False)
    return c.Mudanca(c.RENOMEACAO, "POST", "/pedidos", lado, a, b, p, p)


def comparar(original, reparado, esperado, *mudancas):
    return cp.comparar(original, reparado, esperado, "teste", list(mudancas), ROTAS)


class EquivalenciaTest(unittest.TestCase):
    ORIG = java('{"a": 1, "b": 2}')

    def test_regra_1_identico_ignorando_espacos(self):
        rep = java('{"a":1,   "b":2}')
        self.assertTrue(comparar(self.ORIG, rep, rep.replace("{", "{ ", 1)).equivalente)

    def test_regra_2_json_em_outra_ordem_e_asserções_em_outra_ordem(self):
        esp = java('{"a": 1, "b": 2}', asserts='.andExpect(jsonPath("$.x").value(1))\n                .andExpect(jsonPath("$.y").value(2))')
        rep = java('{"b": 2, "a": 1}', asserts='.andExpect(jsonPath("$.y").value(2))\n                .andExpect(jsonPath("$.x").value(1))')
        self.assertTrue(comparar(self.ORIG, rep, esp).equivalente)

    def test_corpo_diferente_nao_e_equivalente(self):
        c_ = comparar(self.ORIG, java('{"a": 1, "b": 3}'), java('{"a": 1, "b": 2}'))
        self.assertFalse(c_.equivalente)

    def test_asserção_a_menos_ou_valor_diferente_nao_e_equivalente(self):
        esp = java('{"a": 1}')
        self.assertFalse(comparar(self.ORIG, java('{"a": 1}', asserts='.andExpect(jsonPath("$.id").value(is(2)))'), esp).equivalente)

    def test_status_diferente_nao_e_equivalente(self):
        self.assertFalse(comparar(self.ORIG, java('{"a": 1}', status="isOk()"), java('{"a": 1}')).equivalente)

    def test_regra_3_valor_do_campo_novo_de_outro_valor_do_mesmo_tipo(self):
        esp, rep = java('{"a": 1, "cpf": "123"}'), java('{"a": 1, "cpf": "texto"}')
        self.assertTrue(comparar(java('{"a": 1}'), rep, esp, nova("cpf")).equivalente)

    def test_regra_3_valor_de_outro_tipo_nao_vale(self):
        esp, rep = java('{"a": 1, "cpf": "123"}'), java('{"a": 1, "cpf": 7}')
        self.assertFalse(comparar(java('{"a": 1}'), rep, esp, nova("cpf")).equivalente)

    def test_regra_3_enum_exige_valor_do_enum(self):
        esp = java('{"a": 1, "m": "A"}')
        self.assertTrue(comparar(java('{"a": 1}'), java('{"a": 1, "m": "B"}'), esp,
                                 nova("m", enum=["A", "B"])).equivalente)
        self.assertFalse(comparar(java('{"a": 1}'), java('{"a": 1, "m": "C"}'), esp,
                                  nova("m", enum=["A", "B"])).equivalente)

    def test_regra_3_campo_novo_ausente_no_reparo_nao_vale(self):
        self.assertFalse(comparar(java('{"a": 1}'), java('{"a": 1}'), java('{"a": 1, "cpf": "1"}'),
                                  nova("cpf")).equivalente)

    def test_regra_3_so_vale_para_o_campo_novo_nao_para_outros(self):
        esp, rep = java('{"a": 1, "cpf": "1"}'), java('{"a": 9, "cpf": "texto"}')
        self.assertFalse(comparar(java('{"a": 1}'), rep, esp, nova("cpf")).equivalente)

    def test_regressao_sem_correcao_esperada_fica_nula(self):
        self.assertIsNone(comparar(self.ORIG, java('{"a": 1}'), None).equivalente)

    def test_extracao_que_falha_nao_decide(self):
        quebrado = self.ORIG.replace('"a": 1,', '"a" 1,')
        r = comparar(self.ORIG, self.ORIG, quebrado)
        self.assertIsNone(r.equivalente)
        self.assertTrue(any("não decide" in m for m in r.motivos))


class CenarioTest(unittest.TestCase):
    ORIG = java('{"a": 1, "nome": "x"}')

    def cenario(self, rep, *mudancas):
        return comparar(self.ORIG, rep, None, *mudancas).cenario_alterado

    def test_reparo_que_so_aplica_a_diferenca_nao_troca_cenario(self):
        self.assertFalse(self.cenario(java('{"a": 1, "titulo": "x"}'), renomeia("nome", "titulo")))

    def test_valor_que_a_diferenca_nao_atinge_troca_cenario(self):
        self.assertTrue(self.cenario(java('{"a": 2, "titulo": "x"}'), renomeia("nome", "titulo")))

    def test_renomeacao_com_valor_trocado_troca_cenario(self):
        self.assertTrue(self.cenario(java('{"a": 1, "titulo": "outro"}'), renomeia("nome", "titulo")))

    def test_mudar_status_troca_cenario(self):
        self.assertTrue(self.cenario(java('{"a": 1, "nome": "x"}', status="isOk()")))

    def test_mudar_fixture_troca_cenario(self):
        self.assertTrue(self.cenario(java('{"a": 1, "nome": "x"}', sql="/b.sql")))

    def test_mudar_outro_metodo_troca_cenario(self):
        self.assertTrue(self.cenario(java('{"a": 1, "nome": "x"}', outro="void outro() { x(); }")))

    def test_asserção_sobre_campo_nao_atingido_mudou(self):
        self.assertTrue(self.cenario(java('{"a": 1, "nome": "x"}',
                                          asserts='.andExpect(jsonPath("$.id").value(is(2)))')))

    def test_asserção_renomeada_pela_diferenca_nao_troca(self):
        orig = java('{"a": 1}', asserts='.andExpect(jsonPath("$.nome").value("x"))')
        rep = java('{"a": 1}', asserts='.andExpect(jsonPath("$.titulo").value("x"))')
        r = cp.comparar(orig, rep, None, "teste", [renomeia("nome", "titulo", c.RESPOSTA)], ROTAS)
        self.assertFalse(r.cenario_alterado)

    def test_campo_novo_acrescentado_nao_troca_cenario(self):
        self.assertFalse(self.cenario(java('{"a": 1, "nome": "x", "cpf": "texto"}'), nova("cpf")))

    def test_campo_removido_pela_diferenca_nao_troca_cenario(self):
        rem = c.Mudanca(c.REMOCAO, "POST", "/pedidos", c.REQUISICAO, "nome",
                        antes=c.Propriedade("string", None, None, False))
        self.assertFalse(self.cenario(java('{"a": 1}'), rem))


if __name__ == "__main__":
    unittest.main()
