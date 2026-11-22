"""Erros HTTP da chamada ao Claude (T23i, D104, D108) e leitura da chave. Nenhum teste chama a API paga."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import anthropic
import httpx2

from agente_contrato import cliente_claude as cc

RAIZ = Path(__file__).resolve().parent.parent
CHAVE_FALSA = "chave-de-teste-que-nao-e-real"
PEDIDO = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def erro_http(status: int, **cabecalhos) -> anthropic.APIStatusError:
    resposta = httpx2.Response(status, request=PEDIDO, headers=cabecalhos)
    return anthropic.APIStatusError("mensagem da API", response=resposta, body=None)


def levanta(erro: Exception):
    def funcao(**_):
        raise erro
    return funcao


class TestEFatal(unittest.TestCase):
    def test_4xx_param_a_execucao(self):  # D104 e D108
        for status in (400, 401, 402, 403, 404, 413, 422):
            self.assertTrue(cc.e_fatal(status, False), status)

    def test_429_depende_do_retry_after(self):  # D104: sem retry-after é o teto do tier
        self.assertTrue(cc.e_fatal(429, False))
        self.assertFalse(cc.e_fatal(429, True))

    def test_transitorios(self):
        for status in (408, 409, 500, 502, 503, 529):
            self.assertFalse(cc.e_fatal(status, False), status)


class TestChamarTraduzindo(unittest.TestCase):
    def erro_de(self, excecao: Exception) -> Exception:
        with self.assertRaises((cc.ErroDeRede, cc.ErroFatal)) as ctx:
            cc.chamar_traduzindo(levanta(excecao), model="x")
        return ctx.exception

    def test_devolve_o_resultado_e_a_latencia(self):
        resultado, latencia = cc.chamar_traduzindo(lambda **kw: kw["model"], model="x")
        self.assertEqual(resultado, "x")
        self.assertGreaterEqual(latencia, 0)

    def test_timeout_e_queda_de_conexao_sao_erro_de_rede(self):  # D104: timeout pelo mesmo caminho
        for excecao in (anthropic.APITimeoutError(request=PEDIDO), anthropic.APIConnectionError(request=PEDIDO)):
            erro = self.erro_de(excecao)
            self.assertIsInstance(erro, cc.ErroDeRede)
            self.assertGreaterEqual(erro.latencia_s, 0)

    def test_408_409_5xx_e_429_com_retry_after_sao_erro_de_rede(self):
        for excecao in (erro_http(408), erro_http(409), erro_http(500), erro_http(529),
                        erro_http(429, **{"retry-after": "5"})):
            self.assertIsInstance(self.erro_de(excecao), cc.ErroDeRede)

    def test_outros_4xx_sao_fatais(self):  # D104, D108
        for status in (400, 401, 402, 403, 404, 413, 422, 429):
            self.assertIsInstance(self.erro_de(erro_http(status)), cc.ErroFatal, status)

    def test_o_motivo_traz_o_status(self):
        erro = self.erro_de(erro_http(402))
        self.assertIn("HTTP 402", erro.motivo)
        self.assertIn("mensagem da API", erro.motivo)


class TestCriarSdk(unittest.TestCase):
    def test_timeout_explicito_e_duas_repeticoes(self):  # D104; só constrói, não chama a rede
        sdk = cc.criar_sdk(CHAVE_FALSA)
        self.assertEqual(sdk.timeout, 120)
        self.assertEqual(sdk.max_retries, 2)


class TestLerChave(unittest.TestCase):
    def env(self, conteudo: str | None) -> Path:
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = Path(pasta.name, ".env")
        if conteudo is not None:
            caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def test_le_a_chave_com_aspas_comentarios_e_outras_variaveis(self):
        self.assertEqual(cc.ler_chave(self.env(f'# comentário\nOUTRA=1\n\nANTHROPIC_API_KEY = "{CHAVE_FALSA}"\n')),
                         CHAVE_FALSA)

    def test_arquivo_inexistente(self):
        with self.assertRaisesRegex(cc.ChaveAusente, r"\.env\.example"):
            cc.ler_chave(self.env(None))

    def test_chave_vazia_ou_ausente_nao_vaza_o_conteudo(self):
        for conteudo in ("ANTHROPIC_API_KEY=\n", f"OUTRA={CHAVE_FALSA}\n"):
            with self.assertRaises(cc.ChaveAusente) as ctx:
                cc.ler_chave(self.env(conteudo))
            self.assertNotIn(CHAVE_FALSA, str(ctx.exception))


class TestSegurancaDaChave(unittest.TestCase):
    def ignorado(self, nome: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", nome], cwd=RAIZ).returncode == 0

    def test_env_e_ignorado_e_o_exemplo_nao(self):
        self.assertTrue(self.ignorado(".env"))
        self.assertFalse(self.ignorado(".env.example"))

    def test_nenhum_arquivo_rastreavel_contem_formato_de_chave(self):
        prefixo = "sk-" + "ant-"  # montado aqui para este arquivo não se acusar
        arquivos = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                  cwd=RAIZ, capture_output=True, text=True).stdout.split()
        for nome in arquivos:
            caminho = RAIZ / nome
            if caminho.is_file() and caminho.suffix in (".py", ".md", ".txt", ".json", ".example", ".jsonl", ""):
                self.assertNotIn(prefixo, caminho.read_text(encoding="utf-8", errors="ignore"), nome)


if __name__ == "__main__":
    unittest.main()
