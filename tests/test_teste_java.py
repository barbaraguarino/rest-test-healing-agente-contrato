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


class MetodoTest(unittest.TestCase):
    def test_localiza_o_corpo_ignorando_chaves_em_literais_e_comentarios(self):
        m = tj.localizar_metodo(JAVA, "shouldDecreaseStockWhenOrderIsCreated")
        self.assertEqual(JAVA[m.inicio], "{")
        self.assertEqual(JAVA[m.fim - 1], "}")
        self.assertIn("estoque", JAVA[m.inicio:m.fim])
        self.assertNotIn("outroTeste", JAVA[m.inicio:m.fim])

    def test_metodo_inexistente_falha(self):
        with self.assertRaises(tj.ErroDeAnalise):
            tj.localizar_metodo(JAVA, "naoExiste")

    def test_nome_repetido_falha_em_vez_de_adivinhar(self):
        with self.assertRaises(tj.ErroDeAnalise):
            tj.localizar_metodo(JAVA + JAVA, "outroTeste")


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

    def test_chamada_sem_corpo(self):
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


if __name__ == "__main__":
    unittest.main()
