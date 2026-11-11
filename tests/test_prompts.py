import tempfile
import unittest
from pathlib import Path

from agente_contrato.prompts import carregar


class TestCarregar(unittest.TestCase):
    def test_prompt_vazio_e_recusado(self):
        with tempfile.TemporaryDirectory() as pasta:
            (Path(pasta) / "vazio.md").write_text("  \n")
            with self.assertRaisesRegex(ValueError, "vazio"):
                carregar("vazio", Path(pasta))

    def test_prompt_que_falta_e_recusado(self):
        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(FileNotFoundError):
                carregar("classifier", Path(pasta))



if __name__ == "__main__":
    unittest.main()
