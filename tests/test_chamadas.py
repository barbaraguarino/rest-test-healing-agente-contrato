"""Gabarito: os testes da tag rodada-2 (tests/test_teste_java.py); os do corpo JSON voltaram na T51."""
import unittest

from agente_contrato import teste_java as tj

JAVA = '''\
class PedidoControllerTest {
    // chave solta no comentário: }
    @Test
    void outroTeste() throws Exception {
        mockMvc.perform(get("/produtos/1")).andExpect(status().isOk());
    }

    @Test
    void shouldDecreaseStockWhenOrderIsCreated() throws Exception {
        String s = "texto com } chave";
        mockMvc.perform(post("/pedidos")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "carrinhoId": 103,
                                  "cliente": {"nome": "Ana, S.", "email": "ana@exemplo.com"},
                                  "itens": [{"produtoId": 2, "quantidade": 1}, {"produtoId": 3}],
                                  "modalidadeFrete": "PADRAO"
                                }
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.itens[0].subtotal").value(1));

        mockMvc.perform(get("/produtos/2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.estoque").value(is(3)));
    }
}
'''
ROTAS = {"GET": {"/produtos/{id}"}, "POST": {"/pedidos", "/carrinhos/{id}/itens"}}


class ChamadasTest(unittest.TestCase):
    def setUp(self):
        m = tj.localizar_metodo(JAVA, "shouldDecreaseStockWhenOrderIsCreated")
        self.chamadas = tj.analisar_chamadas(JAVA, m, ROTAS)

    def test_acha_as_duas_chamadas_com_rota_e_status(self):
        self.assertEqual([(c.metodo_http, c.url, c.rota, c.status_esperado) for c in self.chamadas],
                         [("POST", "/pedidos", "/pedidos", 201),
                          ("GET", "/produtos/2", "/produtos/{id}", 200)])

    def test_assercao_fica_na_chamada_certa(self):
        self.assertEqual([[a.expressao for a in c.assercoes] for c in self.chamadas],
                         [["$.itens[0].subtotal"], ["$.estoque"]])

    def test_posicoes_da_assercao_apontam_para_a_expressao(self):
        a = self.chamadas[1].assercoes[0]
        self.assertEqual(JAVA[a.ini_expressao:a.fim_expressao], "$.estoque")
        self.assertIn("jsonPath", JAVA[a.ini_linha:a.fim_linha])
        self.assertTrue(JAVA[a.ini_linha:a.fim_linha].endswith("\n"))

    def test_corpo_json_so_na_chamada_que_tem_content(self):
        self.assertEqual(self.chamadas[0].corpo.tipo, "objeto")
        self.assertIsNone(self.chamadas[1].corpo)


class CorpoJsonTest(unittest.TestCase):
    def setUp(self):
        m = tj.localizar_metodo(JAVA, "shouldDecreaseStockWhenOrderIsCreated")
        self.corpo = tj.analisar_chamadas(JAVA, m, ROTAS)[0].corpo

    def _texto(self, membro):
        return JAVA[membro.ini:membro.fim]

    def test_membro_simples_e_aninhado(self):
        [m] = tj.localizar_membros(self.corpo, "modalidadeFrete")
        self.assertEqual(self._texto(m), '"modalidadeFrete": "PADRAO"')
        [m] = tj.localizar_membros(self.corpo, "cliente.nome")
        self.assertEqual(self._texto(m), '"nome": "Ana, S."')  # vírgula dentro da string

    def test_membro_dentro_de_array_devolve_todos_os_que_existem(self):
        achados = tj.localizar_membros(self.corpo, "itens[].quantidade")
        self.assertEqual([self._texto(m) for m in achados], ['"quantidade": 1'])
        self.assertEqual(len(tj.localizar_membros(self.corpo, "itens[].produtoId")), 2)

    def test_caminho_inexistente_devolve_lista_vazia(self):
        self.assertEqual(tj.localizar_membros(self.corpo, "cliente.cpf"), [])
        self.assertEqual(tj.localizar_membros(self.corpo, "naoExiste.x"), [])

    def test_objetos_para_insercao(self):
        [raiz] = tj.localizar_objetos(self.corpo, "")
        self.assertEqual(JAVA[raiz.ini], "{")
        [cliente] = tj.localizar_objetos(self.corpo, "cliente")
        self.assertEqual(JAVA[cliente.fim - 1], "}")
        self.assertEqual(len(tj.localizar_objetos(self.corpo, "itens[]")), 2)

    def test_json_invalido_falha(self):
        with self.assertRaises(tj.ErroDeAnalise):
            tj.analisar_json('{"a" 1}', 0)
        with self.assertRaises(tj.ErroDeAnalise):
            tj.analisar_json('{"a": 1', 0)


class RotaEExpressaoTest(unittest.TestCase):
    def test_resolver_rota(self):
        self.assertEqual(tj.resolver_rota("POST", "/carrinhos/103/itens", ROTAS), "/carrinhos/{id}/itens")
        self.assertIsNone(tj.resolver_rota("GET", "/carrinhos/103/itens", ROTAS))
        self.assertIsNone(tj.resolver_rota("POST", "/pedidos/1/outro", ROTAS))

    def test_caminho_da_expressao(self):
        casos = {"$.estoque": "estoque", "$.itens[0].subtotal": "itens[].subtotal",
                 "$.itens[*].quantidade": "itens[].quantidade", "$[*].sku": "[].sku",
                 "$[0].descricao": "[].descricao", "$.cliente.nome": "cliente.nome"}
        for expressao, esperado in casos.items():
            self.assertEqual(tj.caminho_da_expressao(expressao), esperado)

    def test_expressao_atinge_o_campo_e_o_que_esta_dentro_dele(self):
        self.assertTrue(tj.expressao_atinge("$.estoque", "estoque"))
        self.assertTrue(tj.expressao_atinge("$.itens[0].subtotal", "itens"))
        self.assertTrue(tj.expressao_atinge("$.cliente.nome", "cliente"))
        self.assertFalse(tj.expressao_atinge("$.estoqueMinimo", "estoque"))


if __name__ == "__main__":
    unittest.main()
