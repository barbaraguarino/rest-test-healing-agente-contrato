import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2

from agente_contrato import chamada_llm as cl
from agente_contrato import saida

RAIZ = Path(__file__).resolve().parent.parent
CHAVE_FALSA = "chave-de-teste-que-nao-e-real"


def _http(status: int, **cabecalhos):
    pedido = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return pedido, httpx2.Response(status, request=pedido, headers=cabecalhos)


def _erro_http(status: int, **cabecalhos) -> anthropic.APIStatusError:
    _, resposta = _http(status, **cabecalhos)
    return anthropic.APIStatusError("mensagem da API", response=resposta, body=None)


class SdkFalso:
    """Imita só o que o ClienteAnthropic usa de `anthropic.Anthropic`."""

    def __init__(self, resultado=None, erro: Exception | None = None):
        self.recebido = {}
        self._resultado, self._erro = resultado, erro
        self.messages = SimpleNamespace(create=self._create, count_tokens=self._count)

    def _create(self, **kw):
        self.recebido = kw
        if self._erro:
            raise self._erro
        return self._resultado

    def _count(self, **kw):
        self.recebido = kw
        if self._erro:
            raise self._erro
        return SimpleNamespace(input_tokens=4321)


def _mensagem(thinking_tokens=None, blocos=None, stop_reason="end_turn"):
    detalhes = None if thinking_tokens is None else SimpleNamespace(thinking_tokens=thinking_tokens)
    return SimpleNamespace(
        content=blocos if blocos is not None else [SimpleNamespace(type="text", text='{"rotulo":"legitima"}')],
        stop_reason=stop_reason, model="claude-haiku-5-5", _request_id="req_abc",
        usage=SimpleNamespace(input_tokens=6000, output_tokens=700, output_tokens_details=detalhes))


class ClassificarErroTest(unittest.TestCase):
    def test_erros_que_repetir_nao_resolve(self):
        for status in (400, 401, 402, 403, 404, 413, 422):
            self.assertTrue(cl.e_fatal(status, False), status)

    def test_429_sem_retry_after_e_teto_do_tier_e_com_retry_after_e_transitorio(self):
        self.assertTrue(cl.e_fatal(429, False))
        self.assertFalse(cl.e_fatal(429, True))

    def test_erros_transitorios(self):
        for status in (408, 409, 500, 502, 503, 529):
            self.assertFalse(cl.e_fatal(status, False), status)


class ChamarTest(unittest.TestCase):
    def test_parametros_enviados(self):
        sdk = SdkFalso(_mensagem())
        cl.ClienteAnthropic("x", sdk).chamar("SISTEMA", "USUARIO", saida.SCHEMA_CLASSIFIER)
        r = sdk.recebido
        self.assertEqual(r["model"], "claude-haiku-5-5")
        self.assertEqual(r["max_tokens"], 16000)
        self.assertEqual(r["system"], "SISTEMA")
        self.assertEqual(r["messages"], [{"role": "user", "content": "USUARIO"}])
        self.assertEqual(r["output_config"],
                         {"effort": "medium", "format": {"type": "json_schema", "schema": saida.SCHEMA_CLASSIFIER}})

    def test_nao_envia_temperatura_nem_amostragem_nem_prefill(self):
        sdk = SdkFalso(_mensagem())
        cl.ClienteAnthropic("x", sdk).chamar("s", "u", {})
        for proibido in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice"):
            self.assertNotIn(proibido, sdk.recebido)
        self.assertEqual(sdk.recebido["messages"][-1]["role"], "user")

    def test_converte_a_resposta(self):
        r = cl.ClienteAnthropic("x", SdkFalso(_mensagem(thinking_tokens=300))).chamar("s", "u", {})
        self.assertEqual((r.texto, r.stop_reason, r.modelo, r.request_id),
                         ('{"rotulo":"legitima"}', "end_turn", "claude-haiku-5-5", "req_abc"))
        self.assertEqual((r.uso.input_tokens, r.uso.output_tokens, r.uso.thinking_tokens), (6000, 700, 300))
        self.assertGreaterEqual(r.latencia_s, 0)

    def test_sem_detalhes_de_thinking_o_campo_fica_nulo(self):
        r = cl.ClienteAnthropic("x", SdkFalso(_mensagem(thinking_tokens=None))).chamar("s", "u", {})
        self.assertIsNone(r.uso.thinking_tokens)

    def test_o_texto_vem_do_bloco_de_texto_e_ignora_o_thinking(self):
        blocos = [SimpleNamespace(type="thinking", thinking="raciocínio"), SimpleNamespace(type="text", text="{}")]
        self.assertEqual(cl.ClienteAnthropic("x", SdkFalso(_mensagem(blocos=blocos))).chamar("s", "u", {}).texto, "{}")

    def test_sem_bloco_de_texto_o_texto_e_nulo(self):
        r = cl.ClienteAnthropic("x", SdkFalso(_mensagem(blocos=[], stop_reason="refusal"))).chamar("s", "u", {})
        self.assertIsNone(r.texto)
        self.assertEqual(r.stop_reason, "refusal")

    def test_contar_tokens(self):
        sdk = SdkFalso()
        self.assertEqual(cl.ClienteAnthropic("x", sdk).contar_tokens("sis", "usu"), 4321)
        self.assertEqual(sdk.recebido["model"], "claude-haiku-5-5")
        self.assertEqual(sdk.recebido["system"], "sis")

    def test_cliente_real_usa_timeout_e_retries_da_d104(self):
        cliente = cl.ClienteAnthropic(CHAVE_FALSA)  # só constrói; não chama a rede
        self.assertEqual(cliente._sdk.timeout, 120)
        self.assertEqual(cliente._sdk.max_retries, 2)


class TraducaoDeErrosTest(unittest.TestCase):
    def _erro(self, excecao):
        with self.assertRaises((cl.ErroDeRede, cl.ErroFatal)) as ctx:
            cl.ClienteAnthropic("x", SdkFalso(erro=excecao)).chamar("s", "u", {})
        return ctx.exception

    def test_timeout_e_queda_de_conexao_sao_erro_de_rede(self):
        pedido, _ = _http(200)
        for e in (anthropic.APITimeoutError(request=pedido), anthropic.APIConnectionError(request=pedido)):
            erro = self._erro(e)
            self.assertIsInstance(erro, cl.ErroDeRede)
            self.assertGreaterEqual(erro.latencia_s, 0)

    def test_5xx_e_429_com_retry_after_sao_erro_de_rede(self):
        self.assertIsInstance(self._erro(_erro_http(500)), cl.ErroDeRede)
        self.assertIsInstance(self._erro(_erro_http(529)), cl.ErroDeRede)
        self.assertIsInstance(self._erro(_erro_http(429, **{"retry-after": "5"})), cl.ErroDeRede)

    def test_400_402_e_429_sem_retry_after_sao_fatais(self):
        for status in (400, 401, 402, 403):
            self.assertIsInstance(self._erro(_erro_http(status)), cl.ErroFatal, status)
        self.assertIsInstance(self._erro(_erro_http(429)), cl.ErroFatal)

    def test_o_motivo_traz_o_status_sem_dados_da_requisicao(self):
        erro = self._erro(_erro_http(402))
        self.assertIn("HTTP 402", erro.motivo)
        self.assertIn("mensagem da API", erro.motivo)


class LerChaveTest(unittest.TestCase):
    def _env(self, conteudo: str | None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        caminho = Path(tmp.name, ".env")
        if conteudo is not None:
            caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def test_le_a_chave_com_aspas_comentarios_e_outras_variaveis(self):
        env = self._env(f'# comentário\nOUTRA=1\n\nANTHROPIC_API_KEY = "{CHAVE_FALSA}"\n')
        self.assertEqual(cl.ler_chave(env), CHAVE_FALSA)

    def test_arquivo_inexistente(self):
        with self.assertRaises(cl.ChaveAusente) as ctx:
            cl.ler_chave(self._env(None))
        self.assertIn(".env.example", str(ctx.exception))

    def test_chave_vazia_ou_ausente_nao_vaza_o_conteudo_do_arquivo(self):
        for conteudo in ("ANTHROPIC_API_KEY=\n", f"OUTRA={CHAVE_FALSA}\n"):
            with self.assertRaises(cl.ChaveAusente) as ctx:
                cl.ler_chave(self._env(conteudo))
            self.assertNotIn(CHAVE_FALSA, str(ctx.exception))


class SegurancaDaChaveTest(unittest.TestCase):
    def _ignorado(self, nome: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", nome], cwd=RAIZ).returncode == 0

    def test_env_e_ignorado_pelo_git_e_o_exemplo_nao(self):
        self.assertTrue(self._ignorado(".env"))
        self.assertFalse(self._ignorado(".env.example"))

    def test_o_exemplo_nao_tem_valor(self):
        linhas = [l for l in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
                  if l.startswith("ANTHROPIC_API_KEY")]
        self.assertEqual(linhas, ["ANTHROPIC_API_KEY="])

    def test_nenhum_arquivo_rastreavel_contem_formato_de_chave(self):
        prefixo = "sk-" + "ant-"  # montado aqui para este arquivo não se acusar
        arquivos = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                  cwd=RAIZ, capture_output=True, text=True).stdout.split()
        for nome in arquivos:
            caminho = RAIZ / nome
            if caminho.suffix in (".py", ".md", ".txt", ".json", ".example", ".jsonl", ""):
                self.assertNotIn(prefixo, caminho.read_text(encoding="utf-8", errors="ignore"), nome)


if __name__ == "__main__":
    unittest.main()
