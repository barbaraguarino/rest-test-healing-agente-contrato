"""Roda processos externos (o Maven) com limite de tempo (T23b, D111, D118)."""
import os
import shutil
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

LIMITE_TESTE_S = 120  # D111(a): uma chamada do mvnw
ESPERA_DO_SIGTERM_S = 5


@dataclass
class ResultadoProcesso:
    codigo_saida: int | None  # None quando o tempo estourou
    saida: str
    estourou_tempo: bool


def encerrar_grupo(proc: subprocess.Popen) -> None:
    """Encerra o processo e tudo o que ele abriu, tolerando quem já terminou sozinho."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(ESPERA_DO_SIGTERM_S)
        except subprocess.TimeoutExpired:
            pass
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def rodar_com_limite(comando: list[str], limite_s: float, cwd: Path | None = None) -> ResultadoProcesso:
    """Roda o comando e, se passar de `limite_s`, encerra o processo e os filhos."""
    proc = subprocess.Popen(comando, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    try:
        saida, _ = proc.communicate(timeout=limite_s)
    except subprocess.TimeoutExpired:
        encerrar_grupo(proc)
        saida, _ = proc.communicate()
        return ResultadoProcesso(None, saida, True)
    return ResultadoProcesso(proc.returncode, saida, False)


class ErroDeExecucao(Exception):
    """Falha da infraestrutura de execução; `codigo` é o valor do campo `erro` da D74."""

    def __init__(self, mensagem: str, codigo: str = "erro_execucao"):
        super().__init__(mensagem)
        self.codigo = codigo


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
    """Aplica o patch do caso na cópia; se ele não encaixa, não muda nada."""
    _git("apply", "--check", str(patch), cwd=raiz)
    _git("apply", str(patch), cwd=raiz)


@dataclass(frozen=True)
class RelatorioSurefire:
    executados: int
    falhas: int
    erros: int
    ignorados: int
    tempo_s: float


def ler_relatorios(pasta: Path) -> RelatorioSurefire:
    """Soma os `TEST-*.xml` do Surefire; pasta vazia ou ausente (não compilou) dá tudo zero."""
    soma = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    tempo = 0.0
    for arquivo in sorted(pasta.glob("TEST-*.xml")):
        raiz = ET.parse(arquivo).getroot()
        for campo in soma:
            soma[campo] += int(raiz.get(campo, 0))
        tempo += float(raiz.get("time", 0))
    return RelatorioSurefire(soma["tests"], soma["failures"], soma["errors"], soma["skipped"], tempo)


@dataclass(frozen=True)
class ResultadoTeste:
    compilou: bool
    passou: bool
    duracao_maven_s: float  # relógio de parede da chamada ao Maven, compilação incluída
    duracao_teste_s: float  # tempo do teste, segundo o Surefire; 0 se não compilou


def comando_maven(raiz: Path, classe: str, metodo: str) -> list[str]:
    """Um único método de teste; `Classe*#metodo` inclui as classes @Nested."""
    return [str(raiz / "mvnw"), "-B", f"-Dtest={classe}*#{metodo}", "test"]


def rodar_teste(raiz: Path, classe: str, metodo: str, limite_s: float = LIMITE_TESTE_S,
                comando: list[str] | None = None) -> ResultadoTeste:
    """Roda o teste afetado na cópia; só vale se o Surefire executou exatamente um teste."""
    pasta = raiz / "target" / "surefire-reports"
    shutil.rmtree(pasta, ignore_errors=True)  # nunca ler relatório de uma execução anterior
    inicio = time.monotonic()
    r = rodar_com_limite(comando or comando_maven(raiz, classe, metodo), limite_s, cwd=raiz)
    duracao = time.monotonic() - inicio
    if r.estourou_tempo:
        raise ErroDeExecucao(f"{classe}.{metodo} passou de {limite_s:g}s", "timeout")
    if "COMPILATION ERROR" in r.saida:
        return ResultadoTeste(False, False, duracao, 0.0)
    relatorio = ler_relatorios(pasta)
    if relatorio.executados != 1:
        raise ErroDeExecucao(f"{relatorio.executados} testes executados para {classe}.{metodo}, esperado 1")
    passou = (r.codigo_saida == 0 and relatorio.falhas == 0
              and relatorio.erros == 0 and relatorio.ignorados == 0)
    return ResultadoTeste(True, passou, duracao, relatorio.tempo_s)
