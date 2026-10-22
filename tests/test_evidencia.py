import tempfile
import unittest
from pathlib import Path

from agente_contrato import contrato as c
from agente_contrato import evidencia as ev
from agente_contrato import execucao
from agente_contrato.leitura_falha import Falha

TESTE = '''package x.produto;

class ProdutoControllerTest {
    @Nested
    class Buscar {
        @Test
        @DisplayName("Deve retornar 200")
        void shouldReturn200() throws Exception {
            mockMvc.perform(get("/produtos/1"))
                    .andExpect(jsonPath("$.descricao").value("a"));
        }

        @Test
        void shouldReturn200Outro() { }
    }
}
'''


def _prop(tipo="string", enum=None, obrigatoria=False, formato=None):
    return c.Propriedade(tipo, formato, enum, obrigatoria)


class DescreverMudancasTest(unittest.TestCase):
    def test_um_texto_para_cada_tipo(self):
        mudancas = [
            c.Mudanca(c.RENOMEACAO, "GET", "/p", c.RESPOSTA, "descricao", "resumo", _prop(), _prop()),
            c.Mudanca(c.REMOCAO, "GET", "/p", c.RESPOSTA, "peso", antes=_prop("integer")),
            c.Mudanca(c.ALTERACAO_TIPO, "POST", "/p", c.REQUISICAO, "preco",
                      antes=_prop("number"), depois=_prop("string")),
            c.Mudanca(c.CAMPO_OBRIGATORIO_NOVO, "POST", "/p", c.REQUISICAO, "sku", depois=_prop()),
        ]
        linhas = ev.descrever_mudancas(mudancas).splitlines()
        self.assertEqual(linhas[0], '- GET /p, resposta: o campo "descricao" foi renomeado para "resumo" (string)')
        self.assertEqual(linhas[1], '- GET /p, resposta: o campo "peso" foi removido (integer)')
        self.assertEqual(linhas[2], '- POST /p, requisicao: o campo "preco" mudou de number para string')
        self.assertEqual(linhas[3], '- POST /p, requisicao: o campo "sku" passou a ser obrigatório (string)')

    def test_enum_e_formato_aparecem(self):
        m = c.Mudanca(c.ALTERACAO_TIPO, "GET", "/p", c.RESPOSTA, "status",
                      antes=_prop("integer", formato="int32"), depois=_prop(enum=("ATIVO", "INATIVO")))
        self.assertIn("integer (int32)", ev.descrever_mudanca(m))
        self.assertIn("valores ['ATIVO', 'INATIVO']", ev.descrever_mudanca(m))

    def test_sem_diferenca_diz_isso_explicitamente(self):
        self.assertIn("não registra nenhuma diferença", ev.descrever_mudancas([]))


class TextoDoMetodoTest(unittest.TestCase):
    def test_inclui_anotacoes_assinatura_e_corpo(self):
        t = ev.texto_do_metodo(TESTE, "shouldReturn200")
        self.assertTrue(t.lstrip().startswith("@Test"))
        self.assertIn('@DisplayName("Deve retornar 200")', t)
        self.assertTrue(t.rstrip().endswith("}"))
        self.assertIn('jsonPath("$.descricao")', t)

    def test_nao_invade_o_metodo_vizinho_de_nome_parecido(self):
        t = ev.texto_do_metodo(TESTE, "shouldReturn200")
        self.assertNotIn("shouldReturn200Outro", t)
        outro = ev.texto_do_metodo(TESTE, "shouldReturn200Outro")
        self.assertIn("@Test", outro)
        self.assertNotIn("DisplayName", outro)


class ArquivosDoModuloTest(unittest.TestCase):
    def _api(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for rel, conteudo in {
            "src/main/java/x/produto/Produto.java": "class Produto {}",
            "src/main/java/x/produto/dto/ProdutoResponse.java": "record ProdutoResponse() {}",
            "src/main/java/x/pedido/Pedido.java": "class Pedido {}",
            "src/test/java/x/produto/ProdutoControllerTest.java": TESTE,
        }.items():
            arquivo = raiz / rel
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(conteudo, encoding="utf-8")
        return raiz

    def test_traz_o_pacote_do_teste_com_subpacotes_e_nada_de_outro_modulo(self):
        raiz = self._api()
        modulo = ev.arquivos_do_modulo(raiz, raiz / "src/test/java/x/produto/ProdutoControllerTest.java")
        self.assertEqual(list(modulo), ["src/main/java/x/produto/Produto.java",
                                        "src/main/java/x/produto/dto/ProdutoResponse.java"])

    def test_nao_inclui_a_classe_de_teste(self):
        raiz = self._api()
        modulo = ev.arquivos_do_modulo(raiz, raiz / "src/test/java/x/produto/ProdutoControllerTest.java")
        self.assertFalse(any("src/test" in k for k in modulo))

    def test_modulo_inexistente_e_erro_de_execucao(self):
        raiz = self._api()
        (raiz / "src/test/java/x/frete").mkdir()
        with self.assertRaises(execucao.ErroDeExecucao):
            ev.arquivos_do_modulo(raiz, raiz / "src/test/java/x/frete/FreteControllerTest.java")


class MontarTest(unittest.TestCase):
    def test_secoes_na_ordem_e_conteudo(self):
        mud = [c.Mudanca(c.RENOMEACAO, "GET", "/p", c.RESPOSTA, "descricao", "resumo", _prop(), _prop())]
        falha = Falha("failure", "java.lang.AssertionError", 'No value at JSON path "$.descricao"')
        texto = ev.montar(mud, falha, "ProdutoControllerTest", "shouldReturn200", TESTE,
                          {"src/main/java/x/produto/Produto.java": "class Produto {}\n"})
        ordem = ["## Diferenças", "## Falha do teste ProdutoControllerTest.shouldReturn200",
                 "## Método de teste", "## Código do módulo", "### src/main/java/x/produto/Produto.java"]
        posicoes = [texto.index(t) for t in ordem]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertIn('Mensagem: No value at JSON path "$.descricao"', texto)

    def test_sem_falha_avisa_que_nao_compilou(self):
        texto = ev.montar([], None, "T", "shouldReturn200", TESTE, {})
        self.assertIn("O teste não compilou", texto)


if __name__ == "__main__":
    unittest.main()
