import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.contrato import carregar, resolver

FICHAS = {"components": {"schemas": {
    "Produto": {"type": "object", "properties": {"nome": {"type": "string"}}},
    "No": {"type": "object", "properties": {"filho": {"$ref": "#/components/schemas/No"}}},
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


if __name__ == "__main__":
    unittest.main()
