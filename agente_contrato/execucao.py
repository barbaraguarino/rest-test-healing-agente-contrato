"""Execução dos casos sobre a API cobaia: cópia limpa da tag, patch e teste afetado.

Código determinístico, compartilhado pela baseline e, no T09, pelo agente: o
LLM nunca roda o Maven por conta própria; quem executa é este módulo.

Regra de segurança: o Surefire responde BUILD SUCCESS mesmo quando o filtro não
casa com nenhum teste ("Tests run: 0"). Por isso um resultado só vale se
exatamente um teste foi executado.

Limites de tempo (D111, provisórios): 120 s por chamada do `mvnw` e 180 s por caso, contados da
falha recebida ao fim do Maven final, sem a espera das chamadas ao LLM. O estouro do Maven
inicial, antes de o agente agir, é infraestrutura (`erro_execucao`, fora das métricas) e o Maven
roda mais uma vez; o estouro do teste final ou do caso é `timeout`, falha do tratamento (D85).
"""

import os
import signal
import subprocess
import shutil
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

LIMITE_TESTE_S = 120  # D111(a): uma chamada do mvnw
LIMITE_CASO_S = 180   # D111(b): o caso, sem a espera do LLM
ESPERA_DO_SIGTERM_S = 5


class ErroDeExecucao(Exception):
    """Falha da infraestrutura de execução; `codigo` é o valor do campo `erro` da D74.

    `causa` vai para a lista de exclusões do log (D111e): `estouro_maven_inicial`,
    `teste_passa_sem_reparo` ou `infraestrutura`; nos estouros, `teste_final` ou `caso`.
    """

    def __init__(self, mensagem: str, codigo: str = "erro_execucao", causa: str = "infraestrutura"):
        super().__init__(mensagem)
        self.codigo, self.causa = codigo, causa


@dataclass(frozen=True)
class Limites:
    teste_s: float = LIMITE_TESTE_S
    caso_s: float = LIMITE_CASO_S
    llm_s: float | None = None  # só na v1; é o timeout da chamada (D104), aplicado em chamada_llm
    relogio: object = field(default=time.monotonic, compare=False, repr=False)  # os testes trocam

    def para_o_log(self) -> dict:
        return {"teste_s": self.teste_s, "caso_s": self.caso_s, "llm_s": self.llm_s}

    def caso(self) -> "LimiteDoCaso":
        return LimiteDoCaso(self.caso_s, self.relogio)


class LimiteDoCaso:
    """Relógio de um caso (D111b): começa quando o agente recebe a falha, depois do Maven inicial."""

    def __init__(self, limite_s: float, relogio=time.monotonic):
        self.limite_s, self._relogio = limite_s, relogio
        self._inicio = relogio()
        self.espera_llm_s = 0.0

    def decorrido(self) -> float:
        return self._relogio() - self._inicio - self.espera_llm_s

    def restante(self) -> float:
        return self.limite_s - self.decorrido()

    @contextmanager
    def fora_da_conta(self):
        """A espera de uma chamada ao LLM, que tem limite próprio (D104) e não entra no do caso."""
        inicio = self._relogio()
        try:
            yield
        finally:
            self.espera_llm_s += self._relogio() - inicio

    def verificar(self) -> None:
        if self.restante() <= 0:
            raise ErroDeExecucao(f"o caso passou de {self.limite_s}s", "timeout", "caso")


@dataclass(frozen=True)
class ResultadoTeste:
    compilou: bool
    passou: bool
    duracao_maven_s: float  # relógio de parede da chamada ao Maven, compilação incluída
    duracao_teste_s: float  # tempo do teste, segundo o relatório do Surefire; 0 se não compilou


def _git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ErroDeExecucao(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def preparar_copia(api_origem: Path, tag: str, destino: Path) -> Path:
    """Clona a API cobaia em `destino` (que não pode existir) e fixa a tag, sem alterações."""
    if destino.exists():
        raise ErroDeExecucao(f"{destino} já existe")
    _git("clone", "-q", str(api_origem), str(destino))
    _git("checkout", "-q", tag, cwd=destino)
    if _git("describe", "--tags", "--exact-match", cwd=destino).strip() != tag:
        raise ErroDeExecucao(f"a cópia não está na tag {tag}")
    return destino


def aplicar_patch(raiz: Path, patch: Path) -> None:
    _git("apply", "--check", str(patch), cwd=raiz)
    _git("apply", str(patch), cwd=raiz)


def arquivo_de_teste(raiz: Path, classe: str) -> Path:
    achados = list((raiz / "src" / "test" / "java").rglob(f"{classe}.java"))
    if len(achados) != 1:
        raise ErroDeExecucao(f"{classe}.java: {len(achados)} arquivos, esperado 1")
    return achados[0]


@dataclass(frozen=True)
class _Relatorio:
    executados: int
    falhas: int
    erros: int
    ignorados: int
    tempo_s: float


def _ler_relatorios(pasta: Path) -> _Relatorio:
    soma = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    tempo = 0.0
    for arquivo in sorted(pasta.glob("TEST-*.xml")):
        raiz = ET.parse(arquivo).getroot()
        for campo in soma:
            soma[campo] += int(raiz.get(campo, 0))
        tempo += float(raiz.get("time", 0))
    return _Relatorio(soma["tests"], soma["failures"], soma["errors"], soma["skipped"], tempo)


def _encerrar_grupo(proc: subprocess.Popen) -> None:
    """Encerra o mvnw e tudo o que ele abriu (o java do Maven e o fork do Surefire).

    `subprocess.run` com timeout só mata o filho direto, e o `communicate` seguinte fica preso
    no pipe que os netos ainda seguram. Aqui o grupo inteiro recebe SIGTERM e, se sobrar
    alguém depois de alguns segundos, SIGKILL.
    """
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(ESPERA_DO_SIGTERM_S)
        except subprocess.TimeoutExpired:
            pass
        os.killpg(proc.pid, signal.SIGKILL)  # netos que ignoraram o SIGTERM ou ficaram sem pai
    except ProcessLookupError:
        pass
    proc.communicate()


def rodar_teste(raiz: Path, classe: str, metodo: str,
                timeout_s: float = LIMITE_TESTE_S) -> ResultadoTeste:
    """Roda um único método de teste. `Classe*#metodo` inclui as classes @Nested."""
    pasta = raiz / "target" / "surefire-reports"
    shutil.rmtree(pasta, ignore_errors=True)  # nunca ler relatório de uma execução anterior
    inicio = time.monotonic()
    proc = subprocess.Popen([str(raiz / "mvnw"), "-B", f"-Dtest={classe}*#{metodo}", "test"],
                            cwd=raiz, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)  # grupo próprio, para o estouro encerrar todos
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _encerrar_grupo(proc)
        raise ErroDeExecucao(f"{classe}.{metodo} passou de {timeout_s:g}s", "timeout", "estouro") from None
    except BaseException:  # Ctrl+C no IntelliJ: não deixar o Maven rodando
        _encerrar_grupo(proc)
        raise
    duracao = time.monotonic() - inicio
    if "COMPILATION ERROR" in stdout + stderr:
        return ResultadoTeste(False, False, duracao, 0.0)
    if not pasta.is_dir():
        raise ErroDeExecucao(f"o Maven não gerou relatório (código {proc.returncode})")
    relatorio = _ler_relatorios(pasta)
    if relatorio.executados != 1:
        raise ErroDeExecucao(f"{relatorio.executados} testes executados para {classe}.{metodo}, esperado 1")
    passou = (proc.returncode == 0 and relatorio.falhas == 0
              and relatorio.erros == 0 and relatorio.ignorados == 0)
    return ResultadoTeste(True, passou, duracao, relatorio.tempo_s)


def rodar_teste_inicial(rodar, raiz: Path, classe: str, metodo: str,
                        timeout_s: float = LIMITE_TESTE_S) -> tuple[ResultadoTeste, int]:
    """Maven inicial, antes de o agente agir (D111e). Devolve o resultado e o número de tentativas.

    Um estouro roda o Maven mais uma vez, sem o `target/` da execução interrompida; dois estouros
    viram `erro_execucao`, fora das métricas. Os outros erros não se repetem: o Maven é determinístico.
    """
    for tentativa in (1, 2):
        try:
            return rodar(raiz, classe, metodo, timeout_s=timeout_s), tentativa
        except ErroDeExecucao as exc:
            if exc.codigo != "timeout":
                raise
            shutil.rmtree(raiz / "target", ignore_errors=True)
    raise ErroDeExecucao(f"o Maven inicial de {classe}.{metodo} passou de {timeout_s:g}s nas 2 tentativas",
                         causa="estouro_maven_inicial")


def rodar_teste_final(rodar, raiz: Path, classe: str, metodo: str, limite: LimiteDoCaso,
                      timeout_s: float = LIMITE_TESTE_S) -> ResultadoTeste:
    """Maven final, depois do reparo, com o menor entre o limite do teste e o que resta do caso.

    O estouro é `timeout` sem reexecução (D111d); `causa` diz qual dos dois limites estourou.
    """
    limite.verificar()
    restante = limite.restante()
    try:
        return rodar(raiz, classe, metodo, timeout_s=min(timeout_s, restante))
    except ErroDeExecucao as exc:
        if exc.codigo != "timeout":
            raise
        causa = "teste_final" if timeout_s <= restante else "caso"
        raise ErroDeExecucao(str(exc), "timeout", causa) from None
