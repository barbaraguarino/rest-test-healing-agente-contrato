"""Testes da baseline (T51, D75, D114): os da tag rodada-2, com a alteração de tipo da resposta na D114."""
import unittest

from agente_contrato import baseline as b
from agente_contrato import contrato as c
from agente_contrato import guarda

ROTAS = {"GET": {"/produtos/{id}"}, "POST": {"/pedidos", "/produtos"}}


def propriedade(tipo, enum=None, obrigatoria=False):
    return c.Propriedade(tipo, None, tuple(enum) if enum else None, obrigatoria)


def mudanca(tipo, lado, caminho, novo_caminho=None, antes=None, depois=None,
            metodo="POST", rota="/pedidos"):
    return c.Mudanca(tipo, metodo, rota, lado, caminho, novo_caminho, antes, depois)


def java(corpo="", asserts=""):
    return f'''class T {{
    void teste() throws Exception {{
        mockMvc.perform(post("/pedidos")
                        .content("""
{corpo}
                                """))
{asserts}
    }}
}}
'''


def reparar(texto, *mudancas):
    return b.reparar(texto, "teste", list(mudancas), ROTAS)


class RequisicaoTest(unittest.TestCase):
    def test_renomeia_a_chave_no_corpo(self):
        t = java('{"cliente": {"nome": "Ana"}, "nome": "x"}',
                 "                .andExpect(status().isCreated());")
        r = reparar(t, mudanca(c.RENOMEACAO, c.REQUISICAO, "cliente.nome", "cliente.titulo"))
        self.assertEqual(r.decisao, b.REPARAR)
        self.assertIn('{"cliente": {"titulo": "Ana"}, "nome": "x"}', r.texto)  # só o aninhado

    def test_remove_primeiro_ultimo_e_unico_membro(self):
        for corpo, esperado in [('{"a": 1, "b": 2}', '{"b": 2}'),
                                ('{"b": 2, "a": 1}', '{"b": 2}'),
                                ('{"a": 1}', '{}')]:
            r = reparar(java(corpo, "                .andExpect(status().isOk());"),
                        mudanca(c.REMOCAO, c.REQUISICAO, "a", antes=propriedade("integer")))
            self.assertIn(esperado, r.texto, corpo)

    def test_remove_ultimo_membro_em_json_multilinha(self):
        corpo = '                                {\n                                  "a": 1,\n                                  "b": 2\n                                }'
        r = reparar(java(corpo, "                .andExpect(status().isOk());"),
                    mudanca(c.REMOCAO, c.REQUISICAO, "b", antes=propriedade("integer")))
        self.assertIn('"a": 1\n                                }', r.texto)

    def test_converte_valor_boolean_para_enum(self):
        for entrada, saida in [("true", '"ATIVO"'), ("false", '"INATIVO"')]:
            r = reparar(java('{"ativo": %s}' % entrada, "                .andExpect(status().isOk());"),
                        mudanca(c.ALTERACAO_TIPO, c.REQUISICAO, "ativo",
                                antes=propriedade("boolean"),
                                depois=propriedade("string", ["ATIVO", "INATIVO"])))
            self.assertIn('{"ativo": %s}' % saida, r.texto)

    def test_acrescenta_campo_obrigatorio_inline_e_multilinha(self):
        m = mudanca(c.CAMPO_OBRIGATORIO_NOVO, c.REQUISICAO, "cliente.cpf",
                    depois=propriedade("string", obrigatoria=True))
        r = reparar(java('{"cliente": {"nome": "Ana"}}', "                .andExpect(status().isOk());"), m)
        self.assertIn('{"cliente": {"nome": "Ana", "cpf": "texto"}}', r.texto)
        multi = '                                {\n                                  "cliente": {\n                                    "nome": "Ana"\n                                  }\n                                }'
        r = reparar(java(multi, "                .andExpect(status().isOk());"), m)
        self.assertIn('"nome": "Ana",\n                                    "cpf": "texto"\n', r.texto)

    def test_nao_duplica_campo_que_ja_existe(self):
        m = mudanca(c.CAMPO_OBRIGATORIO_NOVO, c.REQUISICAO, "cpf",
                    depois=propriedade("string", obrigatoria=True))
        r = reparar(java('{"cpf": "1"}', "                .andExpect(status().isOk());"), m)
        self.assertEqual(r.decisao, b.NAO_REPARAR)

    def test_valores_padrao_por_tipo(self):
        esperado = {"string": '"texto"', "integer": "1", "number": "1.0", "boolean": "true",
                    "array": "[]", "object": "{}"}
        for tipo, valor in esperado.items():
            self.assertEqual(b.valor_padrao(propriedade(tipo)), valor)
        self.assertEqual(b.valor_padrao(propriedade("string", ["A", "B"])), '"A"')
        self.assertIsNone(b.valor_padrao(propriedade("desconhecido")))


class RespostaTest(unittest.TestCase):
    RESP = "                .andExpect(status().isOk())\n"

    def test_renomeia_expressao_jsonpath_em_indices_diferentes(self):
        asserts = (self.RESP + '                .andExpect(jsonPath("$.itens[0].precoUnitario").value(1))\n'
                   '                .andExpect(jsonPath("$.itens[*].precoUnitario").value(2));')
        r = reparar(java("{}", asserts),
                    mudanca(c.RENOMEACAO, c.RESPOSTA, "itens[].precoUnitario", "itens[].preco"))
        self.assertIn('$.itens[0].preco")', r.texto)
        self.assertIn('$.itens[*].preco")', r.texto)
        self.assertNotIn("precoUnitario", r.texto)

    def test_renomeia_objeto_acompanha_asserções_dos_filhos(self):
        asserts = self.RESP + '                .andExpect(jsonPath("$.cliente.nome").value("a"));'
        r = reparar(java("{}", asserts), mudanca(c.RENOMEACAO, c.RESPOSTA, "cliente", "comprador"))
        self.assertIn('$.comprador.nome', r.texto)

    def test_remove_asserção_do_meio(self):
        asserts = (self.RESP + '                .andExpect(jsonPath("$.a").value(1))\n'
                   '                .andExpect(jsonPath("$.b").value(2))\n'
                   '                .andExpect(jsonPath("$.c").value(3));')
        r = reparar(java("{}", asserts), mudanca(c.REMOCAO, c.RESPOSTA, "b", antes=propriedade("integer")))
        self.assertNotIn('"$.b"', r.texto)
        self.assertIn('"$.c").value(3));', r.texto)

    def test_remove_ultima_asserção_passa_o_ponto_e_virgula_para_a_anterior(self):
        asserts = (self.RESP + '                .andExpect(jsonPath("$.a").value(1))\n'
                   '                .andExpect(jsonPath("$.b").value(2));')
        r = reparar(java("{}", asserts), mudanca(c.REMOCAO, c.RESPOSTA, "b", antes=propriedade("integer")))
        self.assertIn('.andExpect(jsonPath("$.a").value(1));\n    }', r.texto)

    def test_remove_as_duas_ultimas_asserções(self):
        asserts = (self.RESP + '                .andExpect(jsonPath("$.a").value(1))\n'
                   '                .andExpect(jsonPath("$.b").value(2))\n'
                   '                .andExpect(jsonPath("$.b.x").value(3));')
        r = reparar(java("{}", asserts), mudanca(c.REMOCAO, c.RESPOSTA, "b", antes=propriedade("object")))
        self.assertIn('.andExpect(jsonPath("$.a").value(1));', r.texto)
        self.assertNotIn("$.b", r.texto)

    def _tipo(self, valor, antes, depois):
        asserts = self.RESP + f'                .andExpect(jsonPath("$.n").value({valor}));'
        return reparar(java("{}", asserts),
                       mudanca(c.ALTERACAO_TIPO, c.RESPOSTA, "n", antes=antes, depois=depois))

    def test_d114_mantem_o_matcher_is_com_o_valor_no_tipo_novo(self):
        r = self._tipo("is(0)", propriedade("integer"), propriedade("string"))
        self.assertIn('jsonPath("$.n").value(is("0")));', r.texto)
        self.assertNotIn('.value("0")', r.texto)  # o literal da v1, que a D113 mostrou errado

    def test_d114_decimal_para_texto_vira_is_com_texto(self):
        r = self._tipo('decimal("89.90")', propriedade("number"), propriedade("string"))
        self.assertIn('jsonPath("$.n").value(is("89.90")));', r.texto)

    def test_d114_decimal_continua_decimal_quando_o_tipo_novo_e_numero(self):
        r = self._tipo('decimal("3.0")', propriedade("number"), propriedade("integer"))
        self.assertIn('jsonPath("$.n").value(decimal("3")));', r.texto)

    def test_d114_is_de_texto_para_numero_continua_is(self):
        r = self._tipo('is("12")', propriedade("string"), propriedade("integer"))
        self.assertIn('jsonPath("$.n").value(is(12)));', r.texto)

    def test_literal_de_texto_para_numero_ganha_matcher_d53(self):
        r = self._tipo('"12"', propriedade("string"), propriedade("integer"))
        self.assertIn('jsonPath("$.n").value(is(12)));', r.texto)
        r = self._tipo('"1.5"', propriedade("string"), propriedade("number"))
        self.assertIn('jsonPath("$.n").value(decimal("1.5")));', r.texto)

    def test_literal_booleano_para_enum_continua_literal(self):
        r = self._tipo("true", propriedade("boolean"), propriedade("string", ["ATIVO", "INATIVO"]))
        self.assertIn('jsonPath("$.n").value("ATIVO"));', r.texto)

    def test_alteracao_de_tipo_sem_regra_nao_repara(self):
        r = self._tipo("is(produto.getId())", propriedade("integer"), propriedade("string"))
        self.assertEqual(r.decisao, b.NAO_REPARAR)
        self.assertIn("nenhuma regra", r.ignoradas[0][1])

    def test_resposta_de_erro_nao_e_editada(self):
        asserts = "                .andExpect(status().is(422))\n" \
                  '                .andExpect(jsonPath("$.a").value(1));'
        r = reparar(java("{}", asserts), mudanca(c.REMOCAO, c.RESPOSTA, "a", antes=propriedade("integer")))
        self.assertEqual(r.decisao, b.NAO_REPARAR)

    def test_linha_com_duas_asserções_falha_em_vez_de_apagar_a_outra(self):
        asserts = self.RESP + '                .andExpect(jsonPath("$.a").value(1)).andExpect(jsonPath("$.b").value(2));'
        with self.assertRaises(b.tj.ErroDeAnalise):
            reparar(java("{}", asserts), mudanca(c.REMOCAO, c.RESPOSTA, "a", antes=propriedade("integer")))


class GuardaTest(unittest.TestCase):
    """O reparo da D114 passa no guarda da develop (D115); o literal da v1 não passaria."""
    RESP = RespostaTest.RESP

    def test_reparo_d114_e_aceito_e_o_literal_da_v1_e_recusado(self):
        t = java("{}", self.RESP + '                .andExpect(jsonPath("$.n").value(is(0)));')
        m = mudanca(c.ALTERACAO_TIPO, c.RESPOSTA, "n", antes=propriedade("integer"),
                    depois=propriedade("string"))
        r = reparar(t, m)
        self.assertTrue(guarda.avaliar(t, r.texto, "teste", [m], ROTAS).aceito)
        v1 = t.replace(".value(is(0))", '.value("0")')
        self.assertFalse(guarda.avaliar(t, v1, "teste", [m], ROTAS).aceito)


class DecisaoTest(unittest.TestCase):
    def test_mudanca_em_outra_rota_nao_repara(self):
        t = java('{"a": 1}', "                .andExpect(status().isOk());")
        r = reparar(t, mudanca(c.REMOCAO, c.REQUISICAO, "a", antes=propriedade("integer"),
                               metodo="GET", rota="/produtos/{id}"))
        self.assertEqual((r.decisao, r.texto), (b.NAO_REPARAR, t))
        self.assertEqual(r.ignoradas[0][1], "a mudança não atinge o teste")

    def test_sem_mudancas_nao_repara(self):
        t = java('{"a": 1}', "                .andExpect(status().isOk());")
        self.assertEqual(reparar(t).decisao, b.NAO_REPARAR)

    def test_mudanca_sem_regra_fica_ignorada_com_motivo(self):
        t = java('{"a": "x"}', "                .andExpect(status().isOk());")
        r = reparar(t, mudanca(c.ALTERACAO_TIPO, c.REQUISICAO, "a", antes=propriedade("string"),
                               depois=propriedade("array")))
        self.assertEqual(r.decisao, b.NAO_REPARAR)
        self.assertIn("nenhuma regra", r.ignoradas[0][1])

    def test_repare_so_o_que_o_teste_contem_e_ignora_o_resto(self):
        t = java('{"a": 1}', "                .andExpect(status().isOk());")
        r = reparar(t, mudanca(c.REMOCAO, c.REQUISICAO, "a", antes=propriedade("integer")),
                    mudanca(c.REMOCAO, c.REQUISICAO, "zzz", antes=propriedade("integer")))
        self.assertEqual((len(r.aplicadas), len(r.ignoradas)), (1, 1))

    def test_e_deterministica(self):
        t = java('{"a": 1, "b": 2}', "                .andExpect(status().isOk());")
        m = mudanca(c.REMOCAO, c.REQUISICAO, "a", antes=propriedade("integer"))
        self.assertEqual(reparar(t, m), reparar(t, m))


class ConversaoTest(unittest.TestCase):
    def test_tabela_de_conversao(self):
        P = propriedade
        casos = [("5", P("integer"), P("string"), '"5"'),
                 ("true", P("boolean"), P("string"), '"true"'),
                 ('"12"', P("string"), P("integer"), "12"),
                 ('"x"', P("string"), P("integer"), None),
                 ('"true"', P("string"), P("boolean"), "true"),
                 ("3", P("integer"), P("number"), "3"),
                 ("3.0", P("number"), P("integer"), "3"),
                 ("3.5", P("number"), P("integer"), None),
                 ("true", P("boolean"), P("string", ["A"]), None)]  # enum com um só valor: sem regra para false
        for literal, antes, depois, esperado in casos:
            self.assertEqual(b.converter(literal, antes, depois), esperado, (literal, antes.tipo, depois.tipo))


if __name__ == "__main__":
    unittest.main()
