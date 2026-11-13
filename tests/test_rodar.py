"""Runner da versão agêntica (T23j), com Maven e LLM simulados: nenhum teste chama a API paga.

A API cobaia é um repositório git pequeno, com tag, contrato e uma classe de teste; o patch do caso
renomeia o campo `sku` para `codigo` no contrato. O "Maven" é uma função: o teste passa quando o
arquivo já fala de `codigo`.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from agente_contrato import rodar as runner
from agente_contrato.cliente_claude import ErroDeRede, ErroFatal, RespostaInvalida
from agente_contrato.execucao import ErroDeExecucao, ResultadoTeste
from agente_contrato.guarda import Veredito
from agente_contrato.laco import RespostaModelo
from agente_contrato.registro_llm import LogDeChamadas, Orcamento, OrcamentoEsgotado
from tests.llm_simulado import FabricaDupla, pede
from tests.relogio_falso import RelogioFalso
from tests.test_preparar_copia import git

ARQUIVO = "src/test/java/loja/ProdutoTest.java"
TESTE = '''package loja;

class ProdutoTest {
    @Test
    void busca() throws Exception {
        mockMvc.perform(get("/produtos/1"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.sku").value("A1"));
    }
}
'''
REPARADO = '''    @Test
    void busca() throws Exception {
        mockMvc.perform(get("/produtos/1"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.codigo").value("A1"));
    }'''


def contrato(campo: str) -> str:
    schema = {"type": "object", "properties": {campo: {"type": "string"}}}
    return json.dumps({"paths": {"/produtos/{id}": {"get": {"responses": {
        "200": {"content": {"application/json": {"schema": schema}}}}}}}}, indent=2) + "\n"


def api_falsa(raiz: Path) -> tuple[Path, Path]:
    """A API cobaia falsa, com a tag `base`, e o patch do caso, fora dela."""
    api = raiz / "api"
    (api / "docs").mkdir(parents=True)
    (api / ARQUIVO).parent.mkdir(parents=True)
    (api / "docs" / "openapi.json").write_text(contrato("sku"), encoding="utf-8")
    (api / ARQUIVO).write_text(TESTE, encoding="utf-8")
    git("init", "-q", cwd=api)
    git("add", ".", cwd=api)
    git("commit", "-q", "-m", "base", cwd=api)
    git("tag", "base", cwd=api)
    (api / "docs" / "openapi.json").write_text(contrato("codigo"), encoding="utf-8")
    patch = raiz / "A1-001.patch"
    patch.write_text(git("diff", cwd=api), encoding="utf-8")
    git("checkout", "-q", "--", ".", cwd=api)
    return api, patch


class MavenFalso:
    """Faz o papel do `execucao.rodar_teste`: o teste passa quando o arquivo usa `codigo`.

    `modos` muda o desfecho de uma chamada, em ordem (ex.: "estouro"); guarda o limite de cada uma.
    """

    def __init__(self, *modos: str, relogio: RelogioFalso | None = None, passo_s: float = 10):
        self.modos, self.limites, self.relogio, self.passo_s = list(modos), [], relogio, passo_s

    def __call__(self, raiz: Path, classe: str, metodo: str, limite_s: float) -> ResultadoTeste:
        self.limites.append(limite_s)
        if self.relogio:
            self.relogio.andar(self.passo_s)
        modo = self.modos.pop(0) if self.modos else "normal"
        if modo == "estouro":
            raise ErroDeExecucao("passou do limite", "timeout")
        if modo == "infra":
            raise ErroDeExecucao("o Maven quebrou")
        if modo == "passa":
            return ResultadoTeste(True, True, 1.0, 0.5)
        passou = '"$.codigo"' in (raiz / ARQUIVO).read_text(encoding="utf-8")
        return ResultadoTeste(True, passou, 1.0, 0.5)


def termina(texto: str) -> RespostaModelo:
    return RespostaModelo(texto)


def rotulo(valor: str) -> RespostaModelo:
    return termina(json.dumps({"rotulo": valor, "justificativa": "ensaio"}))


def legitima_reparada() -> FabricaDupla:
    return FabricaDupla([pede("c1", "ver_diferenca"), rotulo("legitima")],
                        [pede("r1", "salvar_reparo", metodo_reparado=REPARADO), termina("pronto")])


def reparada_e_conferida() -> FabricaDupla:
    """O Repair salva e confere com rodar_teste antes de terminar."""
    return FabricaDupla([rotulo("legitima")],
                        [pede("r1", "salvar_reparo", metodo_reparado=REPARADO), pede("r2", "rodar_teste"),
                         termina("pronto")])


class Modelo:
    """Um modelo que levanta a exceção dada na n-ésima chamada; até lá, segue o roteiro."""

    def __init__(self, roteiro: list, excecao: Exception):
        self.roteiro, self.excecao = list(roteiro), excecao

    def __call__(self, historico):
        if not self.roteiro:
            raise self.excecao
        return self.roteiro.pop(0)


class FabricaComExcecao:
    def __init__(self, classifier: Modelo, repair=None):
        self.modelos = [classifier, repair]

    def __call__(self, sistema, definicoes, formato=None):
        return self.modelos.pop(0)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.api, patch = api_falsa(self.raiz)
        self.caso = runner.Caso("A1-001", patch, "ProdutoTest", "busca")
        self.pasta = self.raiz / "saida"
        self.oraculo = {"A1-001": {"id_caso": "A1-001", "categoria": "renomeacao", "rotulo_oraculo": "legitima"}}

    def caso_unico(self, fabrica, maven=None, **kw):
        return runner.executar_caso(self.caso, self.api, "base", self.raiz / "copia", fabrica, maven or MavenFalso(),
                                    **kw)

    def rodada(self, criar_fabrica, maven=None, casos=None, **kw) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return runner.executar_rodada(casos or [self.caso], self.oraculo, self.api, "base", self.pasta, 1,
                                          criar_fabrica, ("p", "c"), maven or MavenFalso(), aquecer_antes=False,
                                          **kw)

    def resultados(self) -> list[dict]:
        return json.loads((self.pasta / runner.ARQUIVO_RESULTADOS).read_text(encoding="utf-8"))["execucoes"]


class TestCarregarCasos(unittest.TestCase):
    def test_ordem_fixa_por_id_sem_o_rotulo(self):  # D82, D112
        oraculo = {"casos": [{"id_caso": "A1-002", "teste_afetado": "B.m2", "patch": "casos/A1-002.patch"},
                             {"id_caso": "A1-001", "teste_afetado": "A.m1", "patch": "casos/A1-001.patch"}]}
        casos = runner.carregar_casos(oraculo, Path("/repo"))
        self.assertEqual([c.id_caso for c in casos], ["A1-001", "A1-002"])
        self.assertEqual((casos[0].classe, casos[0].metodo), ("A", "m1"))
        self.assertFalse(hasattr(casos[0], "rotulo_oraculo"))

    def test_filtro_de_ids(self):
        oraculo = {"casos": [{"id_caso": i, "teste_afetado": "A.m", "patch": "p"} for i in ("A1-001", "A1-002")]}
        self.assertEqual([c.id_caso for c in runner.carregar_casos(oraculo, Path("/r"), {"A1-002"})], ["A1-002"])


if __name__ == "__main__":
    unittest.main()
