import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.execucao import ErroDeExecucao
from agente_contrato.ferramentas import ver_diferenca
from tests.test_preparar_copia import git


def contrato(propriedades: dict) -> str:
    schema = {"type": "object", "properties": propriedades}
    return json.dumps({"paths": {"/produtos/{id}": {"get": {"responses": {
        "200": {"content": {"application/json": {"schema": schema}}}}}}}})


class TestVerDiferenca(unittest.TestCase):
    """O contrato antigo é o do commit da tag (HEAD da cópia); o novo é o arquivo já com o patch."""

    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self._pasta.cleanup)
        self.raiz = Path(self._pasta.name)
        (self.raiz / "docs").mkdir()
        self.openapi = self.raiz / "docs" / "openapi.json"
        self.openapi.write_text(contrato({"sku": {"type": "string"}}), encoding="utf-8")
        git("init", "-q", cwd=self.raiz)
        git("add", ".", cwd=self.raiz)
        git("commit", "-q", "-m", "tag", cwd=self.raiz)

    def test_sem_patch_no_contrato_nao_ha_diferenca(self):
        self.assertIn("nenhuma diferença", ver_diferenca(self.raiz))

    def test_patch_no_contrato_aparece_no_texto(self):
        self.openapi.write_text(contrato({"codigo": {"type": "string"}}), encoding="utf-8")
        self.assertEqual(ver_diferenca(self.raiz),
                         '- GET /produtos/{id}, resposta: o campo "sku" foi renomeado para "codigo" (string)')

    def test_copia_sem_git_e_erro_de_infraestrutura(self):
        with tempfile.TemporaryDirectory() as outra, self.assertRaises(ErroDeExecucao):
            ver_diferenca(Path(outra))


if __name__ == "__main__":
    unittest.main()
