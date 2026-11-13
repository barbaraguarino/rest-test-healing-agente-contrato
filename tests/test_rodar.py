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


class TestExecutarCaso(Base):
    def test_legitima_reparada_roda_o_maven_final(self):
        maven = MavenFalso()
        e = self.caso_unico(legitima_reparada(), maven)
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", None, True, True))
        self.assertEqual(len(maven.limites), 2)  # inicial e final
        self.assertIn('"$.sku"', e.antes)
        self.assertIn('"$.codigo"', e.depois)

    def test_problema_real_nao_roda_o_maven_final(self):
        maven = MavenFalso()
        e = self.caso_unico(FabricaDupla([rotulo("problema_real")], []), maven)
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("nao_reparar", None, None, False))
        self.assertEqual(len(maven.limites), 1)
        self.assertEqual(e.antes, e.depois)

    def test_a_copia_e_apagada(self):
        self.caso_unico(legitima_reparada())
        self.assertFalse((self.raiz / "copia").exists())

    def test_teste_que_passa_sem_reparo_e_erro_de_infraestrutura(self):
        with self.assertRaises(ErroDeExecucao) as ctx:
            self.caso_unico(legitima_reparada(), MavenFalso("passa"))
        self.assertEqual(ctx.exception.causa, "teste_passa_sem_reparo")

    def test_dois_estouros_do_maven_inicial(self):  # D111e
        with self.assertRaises(ErroDeExecucao) as ctx:
            self.caso_unico(legitima_reparada(), MavenFalso("estouro", "estouro"))
        self.assertEqual(ctx.exception.causa, "estouro_maven_inicial")

    def test_um_estouro_do_maven_inicial_roda_de_novo(self):  # D111e
        e = self.caso_unico(legitima_reparada(), MavenFalso("estouro"))
        self.assertEqual((e.tentativas_maven_inicial, e.passou), (2, True))

    def test_estouro_do_maven_final_e_timeout(self):  # D111d, D118
        e = self.caso_unico(legitima_reparada(), MavenFalso("normal", "estouro"))
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", "timeout", False, False))

    def test_maven_final_com_o_que_resta_do_caso(self):  # D111, D123
        relogio = RelogioFalso()
        maven = MavenFalso(relogio=relogio, passo_s=70)
        self.caso_unico(reparada_e_conferida(), maven, agora=relogio)
        # inicial: 120 (o relógio do caso ainda não começou); rodar_teste do Repair: 120; final: 180 - 70
        self.assertEqual(maven.limites, [120, 120, 110])

    def test_tempo_do_caso_acaba_depois_do_reparo_salvo(self):  # D111d, D130: timeout, sem Maven final
        relogio = RelogioFalso()
        maven = MavenFalso(relogio=relogio, passo_s=50)
        e = self.caso_unico(reparada_e_conferida(), maven, agora=relogio, limite_caso_s=40)
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", "timeout", None, False))
        self.assertEqual(len(maven.limites), 2)

    def test_sem_tempo_o_maven_final_nao_roda(self):  # D111d: limite zero é timeout, sem chamar o Maven
        relogio = RelogioFalso()
        caso_esgotado = runner.RelogioCaso(10, relogio)
        relogio.andar(11)
        maven = MavenFalso()
        fim = runner._maven_final(maven, self.raiz, self.caso, caso_esgotado, runner.Fim("reparar", None))
        self.assertEqual(fim, (False, False, runner.Fim("reparar", "timeout")))
        self.assertEqual(maven.limites, [])

    def test_resposta_invalida_no_classifier(self):  # D132
        e = self.caso_unico(FabricaComExcecao(Modelo([], RespostaInvalida("max_tokens", "cortada"))))
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.detalhe), ("nao_reparar", "max_tokens", None,
                                                                             "cortada"))
        self.assertIsNone(e.agente)

    def test_resposta_invalida_depois_do_reparo_aceito(self):  # D132: vale o reparo, e o Maven final roda
        fabrica = FabricaComExcecao(Modelo([rotulo("legitima")], RespostaInvalida("x", "")),
                                    Modelo([pede("r1", "salvar_reparo", metodo_reparado=REPARADO)],
                                           RespostaInvalida("saida_invalida", "refusal")))
        e = self.caso_unico(fabrica)
        self.assertEqual((e.fim.decisao, e.fim.erro, e.compilou, e.passou), ("reparar", "saida_invalida", True, True))

    def test_guarda_recusa_o_arquivo_final(self):  # D129: defeito do código, erro_execucao
        recusa = mock.patch.object(runner, "guarda_do_caso", return_value=lambda final: Veredito(False, ("x",)))
        with recusa, self.assertRaises(ErroDeExecucao) as ctx:
            self.caso_unico(legitima_reparada())
        self.assertEqual(ctx.exception.causa, "guarda_final")

    def test_erros_do_llm_atravessam(self):
        for erro in (ErroDeRede("conexão", 1.0), ErroFatal("HTTP 401", 0.1)):
            with self.subTest(erro=type(erro).__name__), self.assertRaises(type(erro)):
                self.caso_unico(FabricaComExcecao(Modelo([], erro)))


class TestReexecucao(Base):
    def executar(self, *fabricas):
        fila = list(fabricas)
        with redirect_stdout(io.StringIO()):
            return runner.com_reexecucao(self.caso, 1, self.api, "base", self.raiz, lambda i, r: fila.pop(0),
                                         MavenFalso())

    def test_erro_de_rede_reexecuta_uma_vez(self):  # D104
        e = self.executar(FabricaComExcecao(Modelo([], ErroDeRede("timeout", 120))), legitima_reparada())
        self.assertEqual((e.tentativas, e.fim.erro, e.passou), (2, None, True))

    def test_dois_erros_de_rede_sao_erro_llm(self):  # D104
        e = self.executar(*(FabricaComExcecao(Modelo([], ErroDeRede("timeout", 120))) for _ in range(2)))
        self.assertEqual((e.fim.decisao, e.fim.erro, e.causa, e.tentativas), ("nao_reparar", "erro_llm", "erro_llm", 2))

    def test_infraestrutura_e_erro_execucao(self):  # D111e, D124
        with redirect_stdout(io.StringIO()):
            e = runner.com_reexecucao(self.caso, 1, self.api, "base", self.raiz, lambda i, r: legitima_reparada(),
                                      MavenFalso("infra"))
        self.assertEqual((e.fim.erro, e.causa), ("erro_execucao", "infraestrutura"))


class TestTrava(unittest.TestCase):
    def test_confere_antes_de_cada_chamada(self):  # D105
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "chamadas.jsonl"
            chamadas = []
            criar = runner.com_trava(lambda s, defs, formato=None: (lambda h: chamadas.append(h) or "ok"),
                                     Orcamento(0.01, log))
            modelo = criar("sistema", [])
            self.assertEqual(modelo(["oi"]), "ok")
            log.write_text(json.dumps({"id_caso": "A", "repeticao": 1, "custo_usd": 0.02, "input_tokens": 1,
                                       "output_tokens": 1}) + "\n", encoding="utf-8")
            with self.assertRaises(OrcamentoEsgotado):
                modelo(["de novo"])
            self.assertEqual(len(chamadas), 1)  # a segunda nem saiu

    def test_repassa_o_formato(self):  # D131: o Classifier manda o schema
        recebidos = []
        criar = runner.com_trava(lambda s, defs, formato=None: recebidos.append(formato), Orcamento(1, Path("x")))
        criar("sistema", [], formato={"type": "object"})
        self.assertEqual(recebidos, [{"type": "object"}])


if __name__ == "__main__":
    unittest.main()
