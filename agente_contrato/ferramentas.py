"""Ferramentas do agente (T23e, D62): o modelo pede, o código confere o que é permitido e executa.

O LLM decide qual ferramenta pedir e o que preencher; este código decide o que é permitido e o texto
da resposta. Uma recusa vira ErroDeFerramenta e volta ao modelo como erro (D124).
"""
import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from agente_contrato.contrato import carregar, descrever_mudancas, diferenca, rotas_do_contrato
from agente_contrato.execucao import LIMITE_TESTE_S, ErroDeExecucao, _git, ler_falha
from agente_contrato.guarda import Veredito, avaliar
from agente_contrato.laco import ErroDeFerramenta
from agente_contrato.relogio import RelogioCaso
from agente_contrato.teste_java import ErroDeAnalise, localizar_metodo

LIMITE_LEITURA = 30_000  # caracteres; o maior arquivo permitido da API cobaia tem cerca de 26 mil
CONTRATO = "docs/openapi.json"
ARQUIVOS_DE_DOCS = (CONTRATO, "docs/regras-de-negocio.md")  # D73
PERMITIDOS = "`src/`, `docs/openapi.json` e `docs/regras-de-negocio.md`"
# Começo da resposta de erro do salvar_reparo quando o guarda recusa; o registro procura este texto
# no histórico para dar o código `guarda` (D129, T23h).
RECUSA_DO_GUARDA = "O reparo não foi salvo: o teste ficaria mais fraco"


def ler_arquivo(raiz: Path, caminho: str) -> str:
    """Lê um arquivo da cópia da API, com o caminho relativo à raiz, se a D73 permitir.

    Numa pasta, devolve a lista dos arquivos dela e das subpastas, com os caminhos prontos para pedir.
    """
    relativo = PurePosixPath(caminho)
    dentro_da_d73 = relativo.parts[:1] == ("src",) or str(relativo) in ARQUIVOS_DE_DOCS
    if relativo.is_absolute() or ".." in relativo.parts or not dentro_da_d73:
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    arquivo = (raiz / relativo).resolve()
    if not arquivo.is_relative_to(raiz.resolve()):  # um link que aponta para fora da cópia
        raise ErroDeFerramenta(f"Leitura não permitida: {caminho}. Só {PERMITIDOS}.")
    if arquivo.is_dir():
        return _listar(raiz.resolve(), arquivo, str(relativo))
    if not arquivo.is_file():
        raise ErroDeFerramenta(f"Arquivo não encontrado: {caminho}")
    texto = arquivo.read_text(encoding="utf-8")
    if len(texto) > LIMITE_LEITURA:
        return texto[:LIMITE_LEITURA] + f"\n[arquivo cortado: {LIMITE_LEITURA} de {len(texto)} caracteres]"
    return texto


def _listar(raiz: Path, pasta: Path, nome: str) -> str:
    """Os arquivos da pasta, em ordem; um atalho que aponta para fora da cópia não aparece."""
    arquivos = sorted(a.relative_to(raiz).as_posix() for a in pasta.rglob("*")
                      if a.is_file() and a.resolve().is_relative_to(raiz))
    if not arquivos:
        return f"A pasta {nome} não tem arquivos."
    return "\n".join([f"Arquivos em {nome}:"] + [f"- {a}" for a in arquivos])


def _contratos(raiz: Path) -> tuple[dict, dict]:
    """O contrato da tag e o contrato depois do patch.

    A cópia é um clone na tag e o patch só muda os arquivos, então o antigo é o do HEAD. Uma falha
    do git não é culpa do modelo: vira ErroDeExecucao e para o caso (D124).
    """
    antigo = json.loads(_git("show", f"HEAD:{CONTRATO}", cwd=raiz))
    return antigo, carregar(raiz / CONTRATO)


def ver_diferenca(raiz: Path) -> str:
    """A evidência do Agente 1 (D62, D122): o contrato da tag comparado com o contrato depois do patch."""
    return descrever_mudancas(diferenca(*_contratos(raiz)))


def rodar_teste(rodar, raiz: Path, classe: str, metodo: str, relogio: RelogioCaso) -> str:
    """Roda sempre o teste afetado (D112), com o menor entre 120 s e o que resta do caso (D111a, D118).

    `rodar` é o `execucao.rodar_teste`, injetável nos testes. O estouro de tempo volta ao modelo como
    erro e o laço segue; uma falha de infraestrutura (ErroDeExecucao) não é culpa dele e para o caso (D124).
    """
    limite_s = relogio.limite_para_teste(LIMITE_TESTE_S)
    try:
        resultado = rodar(raiz, classe, metodo, limite_s)
    except ErroDeExecucao as exc:
        if exc.codigo != "timeout":
            raise
        raise ErroDeFerramenta(f"O teste passou de {limite_s:g} s e foi interrompido.") from None
    if not resultado.compilou:
        return "O teste não compilou."
    if resultado.passou:
        return "O teste passou."
    falha = ler_falha(raiz / "target" / "surefire-reports")
    if falha is None:  # ex.: o teste foi ignorado (@Disabled)
        return "O teste não passou, e o relatório não traz mensagem de falha."
    return f"O teste falhou.\n{falha.tipo} {falha.excecao}: {falha.mensagem}"


def salvar_reparo(raiz: Path, arquivo: str, metodo: str, metodo_reparado: str,
                  conferir: Callable[[str], Veredito]) -> str:
    """Troca só o corpo do método afetado pelo corpo do método que o modelo escreveu (D116, D101).

    Anotações e assinatura ficam as do original, então o modelo não muda o `@Sql` nem o nome do teste.
    Um método que não se acha no texto do modelo volta a ele como erro; no original, é defeito nosso.
    Antes de gravar, `conferir` passa o arquivo reparado pelo guarda (D129): um reparo recusado não é
    gravado e volta ao modelo como erro, com os motivos.
    """
    try:
        novo = localizar_metodo(metodo_reparado, metodo)
    except ErroDeAnalise as exc:
        raise ErroDeFerramenta(f"O reparo não foi salvo: {exc}. Mande o método {metodo} inteiro.") from None
    caminho = raiz / arquivo
    original = caminho.read_bytes().decode("utf-8")  # bytes, para manter as quebras de linha do arquivo
    antigo = localizar_metodo(original, metodo)
    reparado = original[:antigo.inicio] + metodo_reparado[novo.inicio:novo.fim] + original[antigo.fim:]
    veredito = conferir(reparado)
    if not veredito.aceito:
        raise ErroDeFerramenta(f"{RECUSA_DO_GUARDA} (" + "; ".join(veredito.motivos)
                               + "). O arquivo continua como estava.")
    caminho.write_bytes(reparado.encode("utf-8"))
    return f"Reparo salvo no método {metodo}. Use rodar_teste para conferir."


def _texto(nome: str, descricao: str) -> dict:
    return {nome: {"type": "string", "description": descricao}}


# O que o modelo vê de cada ferramenta (formato `tools` da API do Claude). As descrições são parte do
# prompt: em português e versionadas (D70), sem nada do desenho do experimento (D73).
DEFINICOES = [
    {"name": "ler_arquivo",
     "description": f"Lê um arquivo da API, com o caminho relativo à raiz. Só {PERMITIDOS}. "
                    "Numa pasta, lista os arquivos dela.",
     "input_schema": {"type": "object", "required": ["caminho"],
                      "properties": _texto("caminho", "ex.: src/main/java ou docs/openapi.json")}},
    {"name": "ver_diferenca",
     "description": "Mostra o que mudou no contrato OpenAPI desde a versão em que o teste foi escrito.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "rodar_teste",
     "description": "Roda o teste afetado e diz se passou, se não compilou ou por que falhou.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "salvar_reparo",
     "description": "Salva o método de teste afetado reparado. Mande o método inteiro; só o corpo é "
                    "aplicado, e as anotações e a assinatura ficam as do original.",
     "input_schema": {"type": "object", "required": ["metodo_reparado"],
                      "properties": _texto("metodo_reparado", "o método de teste inteiro, em Java")}},
]


def _campo(entrada: dict, nome: str) -> str:
    """Um campo obrigatório do pedido; a API já confere o esquema, mas um pedido sem ele volta como erro."""
    valor = entrada.get(nome)
    if not isinstance(valor, str):
        raise ErroDeFerramenta(f"Falta o campo {nome}, em texto.")
    return valor


def guarda_do_caso(raiz: Path, arquivo: str, metodo: str) -> Callable[[str], Veredito]:
    """O guarda (T23g) preso ao arquivo original, lido agora, antes de qualquer reparo (D129).

    Cada reparo é comparado com esse original, não com o reparo anterior, então reparos em sequência
    não enfraquecem o teste aos poucos. A diferença do contrato só é calculada no primeiro reparo.
    """
    original = (raiz / arquivo).read_bytes().decode("utf-8")
    contexto = {}

    def conferir(reparado: str) -> Veredito:
        if not contexto:
            antigo, novo = _contratos(raiz)
            contexto.update(mudancas=diferenca(antigo, novo), rotas=rotas_do_contrato(novo))
        return avaliar(original, reparado, metodo, contexto["mudancas"], contexto["rotas"])
    return conferir


def montar(raiz: Path, arquivo: str, classe: str, metodo: str, relogio: RelogioCaso, rodar) -> dict:
    """Liga cada nome das DEFINICOES à sua função, com os dados do caso já preenchidos pelo código.

    O modelo só manda a `entrada` de cada pedido; quem usa qual ferramenta (Classifier ou Repair) é a T23f.
    Chamada antes de qualquer reparo, porque o guarda lê o arquivo original nesse momento.
    """
    conferir = guarda_do_caso(raiz, arquivo, metodo)
    return {
        "ler_arquivo": lambda entrada: ler_arquivo(raiz, _campo(entrada, "caminho")),
        "ver_diferenca": lambda entrada: ver_diferenca(raiz),
        "rodar_teste": lambda entrada: rodar_teste(rodar, raiz, classe, metodo, relogio),
        "salvar_reparo": lambda entrada: salvar_reparo(raiz, arquivo, metodo,
                                                       _campo(entrada, "metodo_reparado"), conferir),
    }
