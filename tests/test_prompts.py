import subprocess
import tempfile
import unittest
from pathlib import Path

from agente_contrato import prompts

# D100-d: sem exemplos de casos/, sem dizer que é um experimento nem a proporção 2:1 (D73).
PROIBIDOS = ("experimento", "estudo", "2:1", "proporção", "oráculo", "baseline", "casos/", "A1-", "piloto")


class PromptsDoRepositorioTest(unittest.TestCase):
    def test_os_dois_prompts_existem(self):
        for nome in ("classifier", "repair"):
            self.assertGreater(len(prompts.carregar(nome)), 200, nome)

    def test_nao_revelam_o_desenho_do_estudo_nem_o_oraculo(self):
        for nome in ("classifier", "repair"):
            texto = prompts.carregar(nome).lower()
            for palavra in PROIBIDOS:
                self.assertNotIn(palavra.lower(), texto, f"{nome}: contém {palavra!r}")

    def test_classifier_define_as_duas_classes_e_o_repair_pede_o_metodo_inteiro(self):
        c, r = prompts.carregar("classifier"), prompts.carregar("repair")
        self.assertIn("`legitima`", c)
        self.assertIn("`problema_real`", c)
        self.assertIn("`justificativa`", c)
        self.assertIn("`metodo_reparado`", r)


class CommitDosPromptsTest(unittest.TestCase):
    def _repo(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *cmd], cwd=raiz, check=True)
        (raiz / "prompts").mkdir()
        return raiz

    def _commit(self, raiz: Path) -> str:
        subprocess.run(["git", "add", "-A"], cwd=raiz, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=raiz, check=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_prompt_commitado_devolve_o_hash(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        hash_ = self._commit(raiz)
        self.assertEqual(prompts.commit_dos_prompts(raiz / "prompts"), hash_)

    def test_alteracao_nao_commitada_marca_o_hash(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        hash_ = self._commit(raiz)
        (raiz / "prompts" / "a.md").write_text("outro texto", encoding="utf-8")
        self.assertEqual(prompts.commit_dos_prompts(raiz / "prompts"), hash_ + prompts.SUFIXO_ALTERADO)

    def test_commit_fora_da_pasta_de_prompts_nao_muda_o_hash(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        hash_ = self._commit(raiz)
        (raiz / "outro.txt").write_text("x", encoding="utf-8")
        self._commit(raiz)
        self.assertEqual(prompts.commit_dos_prompts(raiz / "prompts"), hash_)

    def test_arquivo_novo_na_pasta_sem_commit(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        self.assertEqual(prompts.commit_dos_prompts(raiz / "prompts"), "sem-commit" + prompts.SUFIXO_ALTERADO)


class CarregarTest(unittest.TestCase):
    def test_arquivo_vazio_e_erro(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.md").write_text("  \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                prompts.carregar("x", Path(d))


if __name__ == "__main__":
    unittest.main()
