import subprocess
import tempfile
import unittest
from pathlib import Path

from agente_contrato.agentes import (FERRAMENTAS_AGENTE_UNICO, FERRAMENTAS_CLASSIFIER, FERRAMENTAS_REPAIR,
                                     LIMITE_AGENTE_UNICO, LIMITE_CLASSIFIER, LIMITE_REPAIR, LIMITE_TOTAL)
from agente_contrato.prompts import SUFIXO_ALTERADO, carregar, commit_dos_prompts


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
        self.assertIn(f"no máximo {LIMITE_AGENTE_UNICO} respostas", carregar("agente_unico"))  # D67

    def test_cada_prompt_cita_so_as_ferramentas_do_seu_agente(self):
        todas = set(FERRAMENTAS_CLASSIFIER) | set(FERRAMENTAS_REPAIR)
        for nome, suas in (("classifier", FERRAMENTAS_CLASSIFIER), ("repair", FERRAMENTAS_REPAIR),
                           ("agente_unico", FERRAMENTAS_AGENTE_UNICO)):
            texto = carregar(nome)
            for ferramenta in todas:
                self.assertEqual(f"`{ferramenta}`" in texto, ferramenta in suas, f"{nome}: {ferramenta}")

    def test_prompts_nao_citam_o_desenho_do_experimento(self):  # D73
        for nome in ("classifier", "repair", "agente_unico"):
            texto = carregar(nome)
            for proibido in ("matriz-de-cobertura", "README", "casos/", "oráculo", "experimento"):
                self.assertNotIn(proibido, texto, nome)


    def test_agente_unico_tem_as_partes_dos_dois_prompts(self):  # D67: classifica e repara
        unico, classifier, repair = carregar("agente_unico"), carregar("classifier"), carregar("repair")
        for trecho in ("## As duas classes", "Decida pela evidência que encontrar.",
                       '{"rotulo": "legitima ou problema_real"'):
            self.assertIn(trecho, classifier)
            self.assertIn(trecho, unico)
        for trecho in ("Não remova nem enfraqueça asserções.", "mande o método de teste **inteiro**"):
            self.assertIn(trecho, repair)
            self.assertIn(trecho, unico)


class TestCommitDosPrompts(unittest.TestCase):  # D105, iguais aos da v1 (tag rodada-2)
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
        self.assertEqual(commit_dos_prompts(raiz / "prompts"), hash_)

    def test_alteracao_nao_commitada_marca_o_hash(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        hash_ = self._commit(raiz)
        (raiz / "prompts" / "a.md").write_text("outro texto", encoding="utf-8")
        self.assertEqual(commit_dos_prompts(raiz / "prompts"), hash_ + SUFIXO_ALTERADO)

    def test_commit_fora_da_pasta_de_prompts_nao_muda_o_hash(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        hash_ = self._commit(raiz)
        (raiz / "outro.txt").write_text("x", encoding="utf-8")
        self._commit(raiz)
        self.assertEqual(commit_dos_prompts(raiz / "prompts"), hash_)

    def test_arquivo_novo_na_pasta_sem_commit(self):
        raiz = self._repo()
        (raiz / "prompts" / "a.md").write_text("texto", encoding="utf-8")
        self.assertEqual(commit_dos_prompts(raiz / "prompts"), "sem-commit" + SUFIXO_ALTERADO)


if __name__ == "__main__":
    unittest.main()
