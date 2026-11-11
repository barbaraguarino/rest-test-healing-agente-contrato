import tempfile
import unittest
from pathlib import Path

from agente_contrato.agentes import (FERRAMENTAS_CLASSIFIER, FERRAMENTAS_REPAIR, LIMITE_CLASSIFIER,
                                     LIMITE_REPAIR, LIMITE_TOTAL)
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


class TestPromptsVersionados(unittest.TestCase):
    """Os prompts falam dos limites e das ferramentas; se o código mudar, o texto tem de mudar junto."""

    def test_limites_do_texto_iguais_aos_do_codigo(self):
        self.assertIn(f"no máximo {LIMITE_CLASSIFIER} respostas", carregar("classifier"))
        self.assertIn(f"no máximo {LIMITE_REPAIR} respostas", carregar("repair"))
        self.assertLessEqual(LIMITE_CLASSIFIER + LIMITE_REPAIR, LIMITE_TOTAL)  # D62

    def test_cada_prompt_cita_so_as_ferramentas_do_seu_agente(self):
        todas = set(FERRAMENTAS_CLASSIFIER) | set(FERRAMENTAS_REPAIR)
        for nome, suas in (("classifier", FERRAMENTAS_CLASSIFIER), ("repair", FERRAMENTAS_REPAIR)):
            texto = carregar(nome)
            for ferramenta in todas:
                self.assertEqual(f"`{ferramenta}`" in texto, ferramenta in suas, f"{nome}: {ferramenta}")

    def test_prompts_nao_citam_o_desenho_do_experimento(self):  # D73
        for nome in ("classifier", "repair"):
            texto = carregar(nome)
            for proibido in ("matriz-de-cobertura", "README", "casos/", "oráculo", "experimento"):
                self.assertNotIn(proibido, texto, nome)


if __name__ == "__main__":
    unittest.main()
