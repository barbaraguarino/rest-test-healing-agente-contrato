"""Execução dos casos sobre a API cobaia: cópia limpa da tag, patch e teste afetado.

Código determinístico, compartilhado pela baseline e, no T09, pelo agente: o
LLM nunca roda o Maven por conta própria; quem executa é este módulo.

Regra de segurança: o Surefire responde BUILD SUCCESS mesmo quando o filtro não
casa com nenhum teste ("Tests run: 0"). Por isso um resultado só vale se
exatamente um teste foi executado.
"""

import subprocess
import shutil
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_PADRAO_S = 600  # teto de segurança; os limites do estudo são decididos na T33


class ErroDeExecucao(Exception):
    """Falha da infraestrutura de execução; `codigo` é o valor do campo `erro` da D74."""

    def __init__(self, mensagem: str, codigo: str = "erro_execucao"):
        super().__init__(mensagem)
        self.codigo = codigo


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


def rodar_teste(raiz: Path, classe: str, metodo: str,
                timeout_s: float = TIMEOUT_PADRAO_S) -> ResultadoTeste:
    """Roda um único método de teste. `Classe*#metodo` inclui as classes @Nested."""
    pasta = raiz / "target" / "surefire-reports"
    shutil.rmtree(pasta, ignore_errors=True)  # nunca ler relatório de uma execução anterior
    inicio = time.monotonic()
    try:
        proc = subprocess.run([str(raiz / "mvnw"), "-B", f"-Dtest={classe}*#{metodo}", "test"],
                              cwd=raiz, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ErroDeExecucao(f"{classe}.{metodo} passou de {timeout_s}s", "timeout") from None
    duracao = time.monotonic() - inicio
    if "COMPILATION ERROR" in proc.stdout + proc.stderr:
        return ResultadoTeste(False, False, duracao, 0.0)
    if not pasta.is_dir():
        raise ErroDeExecucao(f"o Maven não gerou relatório (código {proc.returncode})")
    relatorio = _ler_relatorios(pasta)
    if relatorio.executados != 1:
        raise ErroDeExecucao(f"{relatorio.executados} testes executados para {classe}.{metodo}, esperado 1")
    passou = (proc.returncode == 0 and relatorio.falhas == 0
              and relatorio.erros == 0 and relatorio.ignorados == 0)
    return ResultadoTeste(True, passou, duracao, relatorio.tempo_s)
