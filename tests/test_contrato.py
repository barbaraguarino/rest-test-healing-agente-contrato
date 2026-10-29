import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.contrato import Propriedade, achatar_schema, carregar, resolver

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


if __name__ == "__main__":
    unittest.main()
