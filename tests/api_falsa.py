"""API cobaia de mentira para testar o runner sem Maven: um repositório Git temporário com tag,
contrato OpenAPI, um módulo em src/main, uma classe de teste e o patch de um caso.

`RodarFalso` substitui `execucao.rodar_teste`: decide o resultado olhando o texto da classe de teste.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agente_contrato import evidencia
from agente_contrato.execucao import ErroDeExecucao, ResultadoTeste

TAG = "t0"
CLASSE, METODO = "ProdutoControllerTest", "alvo"
ARQUIVO_TESTE = "src/test/java/x/produto/ProdutoControllerTest.java"

CONTRATO = {"openapi": "3.1.0",
            "paths": {"/produtos/{id}": {"get": {"responses": {"200": {"content": {"*/*": {
                "schema": {"$ref": "#/components/schemas/ProdutoResponse"}}}}}}}},
            "components": {"schemas": {"ProdutoResponse": {"type": "object", "properties": {
                "id": {"type": "integer"}, "descricao": {"type": "string"}}}}}}

TESTE = '''package x.produto;

class ProdutoControllerTest {
    @Test
    @Sql({"/fixtures/a.sql"})
    void alvo() throws Exception {
        mockMvc.perform(get("/produtos/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(is(1)))
                .andExpect(jsonPath("$.descricao").value("Livro"));
    }
}
'''
MODELO = "class Produto {\n    String descricao;\n}\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _escrever(raiz: Path, relativo: str, texto: str) -> None:
    arquivo = raiz / relativo
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding="utf-8")


@dataclass(frozen=True)
class ApiFalsa:
    api: Path
    patch: Path
    raiz_repo: Path  # pasta com casos/esperado.patch, no papel da raiz do repositório do agente


def criar(pasta: Path) -> ApiFalsa:
    api, raiz_repo = pasta / "api", pasta / "repo"
    api.mkdir()
    (raiz_repo / "casos").mkdir(parents=True)
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(api, *cmd)
    _escrever(api, "docs/openapi.json", json.dumps(CONTRATO, indent=2))
    _escrever(api, "src/main/java/x/produto/Produto.java", MODELO)
    _escrever(api, ARQUIVO_TESTE, TESTE)
    _git(api, "add", "-A")
    _git(api, "commit", "-q", "-m", "base")
    _git(api, "tag", TAG)

    # patch do caso: renomeia descricao -> resumo no contrato e no código
    novo = json.loads(json.dumps(CONTRATO).replace("descricao", "resumo"))
    _escrever(api, "docs/openapi.json", json.dumps(novo, indent=2))
    _escrever(api, "src/main/java/x/produto/Produto.java", MODELO.replace("descricao", "resumo"))
    patch = pasta / "A1-901.patch"
    patch.write_text(_git(api, "diff"), encoding="utf-8")
    _git(api, "checkout", "--", ".")

    # correção esperada: a mesma troca no teste
    _escrever(api, ARQUIVO_TESTE, TESTE.replace("$.descricao", "$.resumo"))
    (raiz_repo / "casos" / "esperado.patch").write_text(_git(api, "diff"), encoding="utf-8")
    _git(api, "checkout", "--", ".")
    return ApiFalsa(api, patch, raiz_repo)


def metodo_original() -> str:
    return evidencia.texto_do_metodo(TESTE, METODO)


def metodo_certo() -> str:
    return metodo_original().replace("$.descricao", "$.resumo")


def metodo_sem_uma_assercao() -> str:
    return metodo_certo().replace('                .andExpect(jsonPath("$.id").value(is(1)))\n', "")


def metodo_que_nao_compila() -> str:
    return metodo_certo().replace('"Livro"', '"Livro" NAOCOMPILA')


ORACULO_LEGITIMO = {"id_caso": "A1-901", "categoria": "renomeacao", "rotulo_oraculo": "legitima",
                    "correcao_esperada": "casos/esperado.patch"}
ORACULO_REGRESSAO = {"id_caso": "A1-901", "categoria": "renomeacao", "rotulo_oraculo": "problema_real",
                     "correcao_esperada": None}


class RodarFalso:
    """Arquivo de teste igual ao original: o teste falha (e o relatório do Surefire é escrito).
    Arquivo alterado: não compila se tiver NAOCOMPILA; senão passa se usar `$.resumo`.

    `duracoes`: duração simulada de cada chamada, em ordem (o padrão é 1 s). Com `relogio`
    (um `RelogioFalso`), a chamada avança o relógio; a que passa de `timeout_s` avança só até
    ele e levanta o `timeout`, como `execucao.rodar_teste`. `timeouts` guarda o que recebeu."""

    def __init__(self, ja_passa: bool = False, duracoes=(), relogio=None):
        self.chamadas = 0
        self.ja_passa = ja_passa
        self.duracoes, self.relogio, self.timeouts = list(duracoes), relogio, []

    def __call__(self, raiz: Path, classe: str, metodo: str, timeout_s: float = 120) -> ResultadoTeste:
        self.chamadas += 1
        self.timeouts.append(timeout_s)
        duracao = self.duracoes.pop(0) if self.duracoes else 1.0
        if self.relogio is not None:
            self.relogio.avancar(min(duracao, timeout_s))
        if duracao > timeout_s:
            raise ErroDeExecucao(f"{classe}.{metodo} passou de {timeout_s:g}s", "timeout", "estouro")
        texto = (raiz / ARQUIVO_TESTE).read_text(encoding="utf-8")
        if texto == TESTE:
            if self.ja_passa:
                return ResultadoTeste(True, True, 1.0, 0.5)
            pasta = raiz / "target" / "surefire-reports"
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / "TEST-x.xml").write_text(
                '<testsuite><testcase name="alvo"><failure message="No value at JSON path &quot;$.descricao&quot;" '
                'type="java.lang.AssertionError"/></testcase></testsuite>', encoding="utf-8")
            return ResultadoTeste(True, False, 1.0, 0.5)
        if "NAOCOMPILA" in texto:
            return ResultadoTeste(False, False, 1.0, 0.0)
        return ResultadoTeste(True, "$.resumo" in texto, 1.0, 0.5)
