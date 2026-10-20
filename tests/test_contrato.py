import copy
import unittest

from agente_contrato import contrato as c


def contrato_base() -> dict:
    return {
        "paths": {
            "/pedidos": {"post": {
                "requestBody": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/PedidoReq"}}}},
                "responses": {
                    "201": {"content": {"*/*": {"schema": {"$ref": "#/components/schemas/PedidoResp"}}}},
                    "422": {"content": {"*/*": {"schema": {"$ref": "#/components/schemas/Erro"}}}},
                }}},
        },
        "components": {"schemas": {
            "PedidoReq": {"type": "object", "required": ["cliente"], "properties": {
                "cliente": {"$ref": "#/components/schemas/Cliente"},
                "modalidade": {"type": "string", "enum": ["PADRAO", "EXPRESSA"]},
                "ativo": {"type": "boolean"},
                "cupom": {"type": "string"}}},
            "Cliente": {"type": "object", "required": ["nome"], "properties": {
                "nome": {"type": "string"}, "email": {"type": "string"}}},
            "PedidoResp": {"type": "object", "properties": {
                "id": {"type": "integer", "format": "int64"},
                "descricao": {"type": "string"},
                "estoque": {"type": "integer", "format": "int32"},
                "itens": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}}},
            "Item": {"type": "object", "properties": {"quantidade": {"type": "integer"}}},
            "Erro": {"type": "object", "properties": {"mensagem": {"type": "string"}}},
        }},
    }


def tipos(mudancas):
    return [(m.tipo, m.lado, m.caminho, m.novo_caminho) for m in mudancas]


class DiferencaTest(unittest.TestCase):
    def setUp(self):
        self.antigo = contrato_base()
        self.novo = copy.deepcopy(self.antigo)
        self.schemas = self.novo["components"]["schemas"]

    def test_contratos_iguais_nao_tem_mudanca(self):
        self.assertEqual(c.diferenca(self.antigo, self.novo), [])

    def test_renomeacao_na_resposta(self):
        props = self.schemas["PedidoResp"]["properties"]
        props["resumo"] = props.pop("descricao")
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.RENOMEACAO, c.RESPOSTA, "descricao", "resumo")])

    def test_renomeacao_de_campo_obrigatorio_na_requisicao(self):
        props = self.schemas["Cliente"]["properties"]
        props["titulo"] = props.pop("nome")
        self.schemas["Cliente"]["required"] = ["titulo"]
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.RENOMEACAO, c.REQUISICAO, "cliente.nome", "cliente.titulo")])

    def test_remocao_e_campo_opcional_novo_sem_par_nao_vira_renomeacao(self):
        props = self.schemas["PedidoResp"]["properties"]
        del props["descricao"]
        props["observacao"] = {"type": "integer"}  # forma diferente: não é par
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.REMOCAO, c.RESPOSTA, "descricao", None)])

    def test_mais_de_um_candidato_nao_adivinha_renomeacao(self):
        props = self.schemas["Cliente"]["properties"]
        del props["email"]
        del props["nome"]
        props["a"] = {"type": "string"}
        props["b"] = {"type": "string"}
        self.schemas["Cliente"]["required"] = []
        self.assertEqual([m.tipo for m in c.diferenca(self.antigo, self.novo)],
                         [c.REMOCAO, c.REMOCAO])

    def test_campo_obrigatorio_novo(self):
        self.schemas["Cliente"]["properties"]["cpf"] = {"type": "string"}
        self.schemas["Cliente"]["required"] = ["nome", "cpf"]
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.CAMPO_OBRIGATORIO_NOVO, c.REQUISICAO, "cliente.cpf", None)])

    def test_campo_opcional_novo_e_ignorado(self):
        self.schemas["Cliente"]["properties"]["apelido"] = {"type": "string"}
        self.assertEqual(c.diferenca(self.antigo, self.novo), [])

    def test_campo_existente_que_virou_obrigatorio(self):
        self.schemas["Cliente"]["required"] = ["nome", "email"]
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.CAMPO_OBRIGATORIO_NOVO, c.REQUISICAO, "cliente.email", None)])

    def test_alteracao_de_tipo_boolean_para_enum(self):
        self.schemas["PedidoReq"]["properties"]["ativo"] = {
            "type": "string", "enum": ["ATIVO", "INATIVO"]}
        [m] = c.diferenca(self.antigo, self.novo)
        self.assertEqual((m.tipo, m.caminho, m.antes.tipo, m.depois.enum),
                         (c.ALTERACAO_TIPO, "ativo", "boolean", ("ATIVO", "INATIVO")))

    def test_mudanca_de_formato_sem_mudar_tipo_e_ignorada(self):
        self.schemas["PedidoResp"]["properties"]["id"]["format"] = "int32"
        self.assertEqual(c.diferenca(self.antigo, self.novo), [])

    def test_campo_dentro_de_array_usa_colchetes(self):
        self.schemas["Item"]["properties"]["quantidade"] = {"type": "string"}
        [m] = c.diferenca(self.antigo, self.novo)
        self.assertEqual((m.tipo, m.caminho), (c.ALTERACAO_TIPO, "itens[].quantidade"))

    def test_remover_objeto_nao_lista_os_filhos(self):
        del self.schemas["PedidoReq"]["properties"]["cliente"]
        self.schemas["PedidoReq"]["required"] = []
        self.assertEqual(tipos(c.diferenca(self.antigo, self.novo)),
                         [(c.REMOCAO, c.REQUISICAO, "cliente", None)])

    def test_resposta_de_erro_nao_entra(self):
        self.schemas["Erro"]["properties"]["codigo"] = {"type": "string"}
        self.assertEqual(c.diferenca(self.antigo, self.novo), [])

    def test_referencia_circular_nao_trava(self):
        self.antigo["components"]["schemas"]["Item"]["properties"]["pai"] = {
            "$ref": "#/components/schemas/Item"}
        self.assertIn(("POST", "/pedidos", c.RESPOSTA), c.achatar(self.antigo))


if __name__ == "__main__":
    unittest.main()
