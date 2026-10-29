import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.contrato import (CAMPO_OBRIGATORIO_NOVO, REMOCAO, RENOMEACAO, Mudanca, Propriedade, achatar,
                                      achatar_schema, carregar, diferenca, resolver)

FICHAS = {"components": {"schemas": {
    "Produto": {"type": "object", "properties": {"nome": {"type": "string"}}},
    "No": {"type": "object", "properties": {"filho": {"$ref": "#/components/schemas/No"}}},
    "Item": {"type": "object", "required": ["quantidade"], "properties": {
        "quantidade": {"type": "integer", "format": "int32"},
        "status": {"type": "string", "enum": ["ATIVO", "INATIVO"]}}},
}}}


class TestCarregar(unittest.TestCase):
    def test_le_o_json_do_contrato(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "openapi.json"
            arquivo.write_text(json.dumps({"openapi": "3.0.1", "título": "ç"}), encoding="utf-8")
            self.assertEqual(carregar(arquivo), {"openapi": "3.0.1", "título": "ç"})


class TestResolver(unittest.TestCase):
    def test_schema_sem_ref_volta_como_esta(self):
        no = {"type": "string"}
        self.assertEqual(resolver(FICHAS, no, ()), (no, ()))

    def test_ref_aponta_para_a_ficha_em_components(self):
        schema, visitados = resolver(FICHAS, {"$ref": "#/components/schemas/Produto"}, ())
        self.assertEqual(schema, FICHAS["components"]["schemas"]["Produto"])
        self.assertEqual(visitados, ("Produto",))

    def test_ref_circular_nao_desce_de_novo(self):
        self.assertEqual(resolver(FICHAS, {"$ref": "#/components/schemas/No"}, ("No",)), ({}, ("No",)))


class TestAchatarSchema(unittest.TestCase):
    def test_objeto_aninhado_vira_caminhos_com_ponto_e_obrigatoria_vem_do_pai(self):
        schema = {"type": "object", "required": ["cliente"], "properties": {
            "cliente": {"type": "object", "properties": {"cep": {"type": "string"}}}}}
        self.assertEqual(achatar_schema(FICHAS, schema), {
            "cliente": Propriedade("object", None, None, True),
            "cliente.cep": Propriedade("string", None, None, False),
        })

    def test_lista_ganha_colchetes_e_segue_o_ref_dos_itens(self):
        schema = {"type": "object", "properties": {
            "itens": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}}}
        self.assertEqual(achatar_schema(FICHAS, schema), {
            "itens": Propriedade("array", None, None, False),
            "itens[]": Propriedade("object", None, None, False),
            "itens[].quantidade": Propriedade("integer", "int32", None, True),
            "itens[].status": Propriedade("string", None, ("ATIVO", "INATIVO"), False),
        })

    def test_ref_circular_para_no_primeiro_retorno(self):
        campos = achatar_schema(FICHAS, {"$ref": "#/components/schemas/No"})
        self.assertEqual(list(campos), ["filho"])
        self.assertEqual(campos["filho"].tipo, "desconhecido")  # a ficha circular volta vazia


class TestAchatarContrato(unittest.TestCase):
    CONTRATO = {"paths": {"/produtos/{id}": {
        "parameters": [{"name": "id", "in": "path"}],  # não é um método HTTP: fica de fora
        "get": {"responses": {
            "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Produto"}}}},
            "404": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}}}},
        "put": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}},
                "responses": {"204": {"description": "sem corpo"}}},
    }}, **FICHAS}

    def test_cada_operacao_tem_a_planilha_da_requisicao_e_da_resposta_2xx(self):
        planilhas = achatar(self.CONTRATO)
        self.assertEqual(sorted(planilhas), [("GET", "/produtos/{id}", "resposta"),
                                             ("PUT", "/produtos/{id}", "requisicao")])
        self.assertEqual(planilhas[("GET", "/produtos/{id}", "resposta")],
                         {"nome": Propriedade("string", None, None, False)})  # o 404 não entra
        self.assertEqual(sorted(planilhas[("PUT", "/produtos/{id}", "requisicao")]), ["quantidade", "status"])


def contrato_com_resposta(propriedades: dict, obrigatorias: tuple = ()) -> dict:
    """Contrato mínimo: só o GET /produtos/{id}, com a resposta 200 dada."""
    schema = {"type": "object", "required": list(obrigatorias), "properties": propriedades}
    return {"paths": {"/produtos/{id}": {"get": {"responses": {
        "200": {"content": {"application/json": {"schema": schema}}}}}}}}


TEXTO = {"type": "string"}
NUMERO = {"type": "number"}
CHAVE = ("GET", "/produtos/{id}", "resposta")


class TestDiferencaRemocaoECampoNovo(unittest.TestCase):
    def test_contratos_iguais_nao_tem_mudanca(self):
        c = contrato_com_resposta({"nome": TEXTO})
        self.assertEqual(diferenca(c, c), [])

    def test_campo_que_sumiu_e_remocao(self):
        antigo = contrato_com_resposta({"nome": TEXTO, "sku": TEXTO})
        novo = contrato_com_resposta({"nome": TEXTO})
        self.assertEqual(diferenca(antigo, novo),
                         [Mudanca(REMOCAO, *CHAVE, "sku", antes=Propriedade("string", None, None, False))])

    def test_filho_de_um_campo_removido_acompanha_o_pai(self):
        endereco = {"type": "object", "properties": {"cep": TEXTO, "rua": TEXTO}}
        antigo = contrato_com_resposta({"nome": TEXTO, "endereco": endereco})
        novo = contrato_com_resposta({"nome": TEXTO})
        self.assertEqual([m.caminho for m in diferenca(antigo, novo)], ["endereco"])

    def test_campo_novo_so_entra_se_for_obrigatorio(self):
        antigo = contrato_com_resposta({"nome": TEXTO})
        novo = contrato_com_resposta({"nome": TEXTO, "sku": TEXTO, "nota": TEXTO}, obrigatorias=("sku",))
        self.assertEqual(diferenca(antigo, novo),
                         [Mudanca(CAMPO_OBRIGATORIO_NOVO, *CHAVE, "sku", depois=Propriedade("string", None, None, True))])



class TestDiferencaRenomeacao(unittest.TestCase):
    def test_um_sai_e_um_entra_com_a_mesma_forma_e_renomeacao(self):
        antigo = contrato_com_resposta({"nome": TEXTO, "sku": TEXTO})
        novo = contrato_com_resposta({"nome": TEXTO, "codigo": TEXTO})
        texto = Propriedade("string", None, None, False)
        self.assertEqual(diferenca(antigo, novo), [Mudanca(RENOMEACAO, *CHAVE, "sku", "codigo", texto, texto)])

    def test_formato_diferente_nao_impede_a_renomeacao(self):
        antigo = contrato_com_resposta({"qtd": {"type": "integer", "format": "int32"}})
        novo = contrato_com_resposta({"quantidade": {"type": "integer", "format": "int64"}})
        self.assertEqual([m.tipo for m in diferenca(antigo, novo)], [RENOMEACAO])

    def test_tipo_diferente_nao_e_renomeacao(self):
        antigo = contrato_com_resposta({"sku": TEXTO})
        novo = contrato_com_resposta({"codigo": NUMERO}, obrigatorias=("codigo",))
        self.assertEqual([(m.tipo, m.caminho) for m in diferenca(antigo, novo)],
                         [(REMOCAO, "sku"), (CAMPO_OBRIGATORIO_NOVO, "codigo")])

    def test_mais_de_um_candidato_nao_adivinha(self):
        antigo = contrato_com_resposta({"sku": TEXTO, "nome": TEXTO})
        novo = contrato_com_resposta({"codigo": TEXTO, "titulo": TEXTO})
        self.assertEqual([m.tipo for m in diferenca(antigo, novo)], [REMOCAO, REMOCAO])  # os novos são opcionais

    def test_renomeacao_so_vale_dentro_do_mesmo_objeto(self):
        antigo = contrato_com_resposta({"sku": TEXTO, "cliente": {"type": "object", "properties": {}}})
        novo = contrato_com_resposta({"cliente": {"type": "object", "properties": {"codigo": TEXTO}}})
        self.assertEqual([(m.tipo, m.caminho) for m in diferenca(antigo, novo)], [(REMOCAO, "sku")])



if __name__ == "__main__":
    unittest.main()
