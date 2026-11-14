import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato.registro import CAMPOS, Fim, gravar_resultados, registrar

LEGITIMO = {"id_caso": "A1-001", "categoria": "renomeacao", "rotulo_oraculo": "legitima"}
REGRESSAO = {"id_caso": "A1-003", "categoria": "renomeacao", "rotulo_oraculo": "problema_real"}

# O validador da T20a fica no repositório de avaliação, ao lado deste (mesma pasta-mãe).
VALIDACAO = Path(__file__).resolve().parents[2] / "rest-test-healing-avaliacao" / "avaliacao" / "validacao.py"


def carregar_validacao():
    spec = importlib.util.spec_from_file_location("validacao_t20a", VALIDACAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class TestRegistrar(unittest.TestCase):
    def test_reparo_que_passou(self):
        r = registrar(Fim("reparar", None), LEGITIMO, 1, compilou=True, passou=True, tempo_s=42.123456,
                      equivalente_oraculo=True, cenario_alterado=False)
        self.assertEqual(tuple(r), CAMPOS)
        self.assertEqual((r["agente"], r["tratamento"], r["versao_agente"]), ("agente1", "agentes", "agentica"))
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["assercoes_enfraquecidas"], r["erro"]),
                         ("reparar", True, True, False, None))
        self.assertEqual(r["tempo_s"], 42.1235)

    def test_sem_comparador_o_veredito_fica_nulo(self):  # D110: revisão manual até a T50
        r = registrar(Fim("reparar", None), LEGITIMO, 1, compilou=True, passou=True, tempo_s=1)
        self.assertEqual((r["equivalente_oraculo"], r["cenario_alterado"]), (None, None))

    def test_nao_reparar_deixa_os_campos_do_reparo_nulos_e_passou_falso(self):  # D74, D102
        r = registrar(Fim("nao_reparar", "guarda"), LEGITIMO, 2, compilou=True, passou=True, tempo_s=1)
        self.assertEqual([r[c] for c in ("compilou", "equivalente_oraculo", "assercoes_enfraquecidas",
                                         "cenario_alterado")], [None] * 4)
        self.assertEqual((r["passou"], r["erro"], r["repeticao"]), (False, "guarda", 2))

    def test_timeout_com_reparo_salvo_e_falha(self):  # D118, D130
        r = registrar(Fim("reparar", "timeout"), LEGITIMO, 1, compilou=True, passou=True, tempo_s=180)
        self.assertEqual((r["decisao"], r["compilou"], r["passou"], r["erro"]), ("reparar", False, False, "timeout"))

    def test_oraculo_copiado_so_no_registro(self):
        r = registrar(Fim("nao_reparar", None), REGRESSAO, 1, compilou=None, passou=False, tempo_s=1)
        self.assertEqual((r["id_caso"], r["categoria"], r["rotulo_oraculo"]),
                         ("A1-003", "renomeacao", "problema_real"))

    def test_baseline_sem_versao_do_agente(self):  # D74, T51
        r = registrar(Fim("reparar", None), LEGITIMO, 1, True, True, 0.01, tratamento="baseline", versao_agente=None)
        self.assertEqual((r["tratamento"], r["versao_agente"], r["tokens"], r["custo_usd"]), ("baseline", None, 0, 0.0))

    def test_mesmo_caso_e_repeticao_em_tratamentos_diferentes_e_gravado(self):  # chave da D74
        a = registrar(Fim("nao_reparar", None), REGRESSAO, 1, compilou=None, passou=False, tempo_s=1)
        b = registrar(Fim("nao_reparar", None), REGRESSAO, 1, compilou=None, passou=False, tempo_s=1,
                      tratamento="baseline", versao_agente=None)
        with tempfile.TemporaryDirectory() as pasta:
            gravar_resultados(Path(pasta) / "resultados-agente1.json", "linha-de-base-2", [a, b])

    def test_execucao_repetida_nao_e_gravada(self):
        r = registrar(Fim("nao_reparar", None), REGRESSAO, 1, compilou=None, passou=False, tempo_s=1)
        with tempfile.TemporaryDirectory() as pasta, self.assertRaises(ValueError):
            gravar_resultados(Path(pasta) / "resultados-agente1.json", "linha-de-base-2", [r, r])


@unittest.skipUnless(VALIDACAO.is_file(), "repositório rest-test-healing-avaliacao não está ao lado deste")
class TestArquivoNoValidadorDaT20a(unittest.TestCase):
    """O arquivo gravado por gravar_resultados passa pelo validador da T20a (avaliacao/validacao.py)."""

    def setUp(self):
        self.validacao = carregar_validacao()

    def gravar_e_validar(self, registros):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "resultados-agente1.json"
            gravar_resultados(caminho, "linha-de-base-2", registros)
            self.assertEqual(json.loads(caminho.read_text(encoding="utf-8"))["versao_api"], "linha-de-base-2")
            return self.validacao.carregar(caminho)

    def exemplo(self, equivalente_oraculo, cenario_alterado):
        """Um arquivo com um registro de cada fim possível (casos fictícios, uma repetição cada)."""
        fins = [Fim("nao_reparar", None), Fim("nao_reparar", "saida_invalida"),
                Fim("nao_reparar", "limite_chamadas"), Fim("nao_reparar", "guarda"),
                Fim("nao_reparar", "timeout")]
        registros = [registrar(fim, {**REGRESSAO, "id_caso": f"X-{i}"}, 1, None, False, 10.0)
                     for i, fim in enumerate(fins)]
        registros.append(registrar(Fim("reparar", None), LEGITIMO, 1, True, True, 50.0,
                                   equivalente_oraculo=equivalente_oraculo, cenario_alterado=cenario_alterado))
        registros.append(registrar(Fim("reparar", "timeout"), {**LEGITIMO, "id_caso": "A1-002"}, 1, True, True,
                                   180.0, equivalente_oraculo=equivalente_oraculo, cenario_alterado=cenario_alterado))
        return registros

    def test_todos_os_fins_sao_aceitos(self):
        self.assertEqual(len(self.gravar_e_validar(self.exemplo(True, False))), 7)

    def test_legitimo_reparado_sem_comparador_fica_pendente(self):  # D110: recusado até a revisão manual
        with self.assertRaises(self.validacao.ArquivoInvalido) as erro:
            self.gravar_e_validar(self.exemplo(None, None))
        self.assertTrue(any("pendente de revisão manual" in p for p in erro.exception.problemas))
        self.assertTrue(any("cenario_alterado nulo" in p for p in erro.exception.problemas))

    def test_baseline_e_agentes_no_mesmo_arquivo(self):  # T51: os nulos da D110 continuam pendentes
        registros = [registrar(Fim("reparar", None), REGRESSAO, 1, True, False, 0.01, cenario_alterado=False,
                               tratamento="baseline", versao_agente=None),
                     registrar(Fim("nao_reparar", "guarda"), {**LEGITIMO, "id_caso": "A1-002"}, 1, None, False, 0.01,
                               tratamento="baseline", versao_agente=None),
                     registrar(Fim("nao_reparar", None), REGRESSAO, 1, None, False, 30.0)]
        self.assertEqual(len(self.gravar_e_validar(registros)), 3)

    def test_problema_real_reparado_aceita_veredito_nulo(self):  # D119
        r = registrar(Fim("reparar", None), REGRESSAO, 1, True, True, 50.0, cenario_alterado=False)
        self.assertEqual(len(self.gravar_e_validar([r])), 1)
