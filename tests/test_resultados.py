import json
import tempfile
import unittest
from pathlib import Path

from agente_contrato import resultados as r


def registro(**mudancas):
    base = {"id_caso": "A1-001", "agente": "agente1", "tratamento": "baseline",
            "versao_agente": None, "categoria": "renomeacao", "rotulo_oraculo": "legitima",
            "decisao": "reparar", "compilou": True, "passou": True, "equivalente_oraculo": True,
            "assercoes_enfraquecidas": False, "cenario_alterado": False, "repeticao": 1,
            "tempo_s": 0.01, "tokens": 0, "custo_usd": 0, "erro": None}
    base.update(mudancas)
    return base


class ValidacaoTest(unittest.TestCase):
    def test_registro_valido(self):
        self.assertEqual(r.problemas(registro()), [])

    def test_nao_reparar_com_nulos(self):
        ok = registro(decisao="nao_reparar", compilou=None, equivalente_oraculo=None,
                      assercoes_enfraquecidas=None, cenario_alterado=None, passou=False)
        self.assertEqual(r.problemas(ok), [])

    def test_nao_reparar_com_compilou_preenchido_e_invalido(self):
        self.assertTrue(r.problemas(registro(decisao="nao_reparar")))

    def test_reparar_sem_compilou_e_invalido(self):
        self.assertTrue(r.problemas(registro(compilou=None)))

    def test_valores_fora_dos_permitidos(self):
        for campo, valor in [("tratamento", "x"), ("rotulo_oraculo", "talvez"), ("erro", "falha"),
                             ("versao_agente", "v2"), ("repeticao", 0), ("passou", None)]:
            self.assertTrue(r.problemas(registro(**{campo: valor})), campo)

    def test_campo_ausente_e_desconhecido(self):
        faltando = registro()
        del faltando["tokens"]
        self.assertEqual(r.problemas(faltando), ["campo ausente: tokens"])
        self.assertEqual(r.problemas({**registro(), "extra": 1}), ["campo desconhecido: extra"])

    def test_regressao_reparada_pode_ter_equivalente_nulo(self):
        self.assertEqual(r.problemas(registro(rotulo_oraculo="problema_real", passou=False,
                                              equivalente_oraculo=None)), [])


class GravarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.arquivo = Path(self._tmp.name) / "saida" / "resultados-agente1.json"

    def test_grava_no_formato_da_d74(self):
        r.gravar(self.arquivo, "linha-de-base-2", [registro(), registro(id_caso="A1-002")])
        dado = json.loads(self.arquivo.read_text(encoding="utf-8"))
        self.assertEqual(list(dado), ["versao_api", "execucoes"])
        self.assertEqual(dado["versao_api"], "linha-de-base-2")
        self.assertEqual(list(dado["execucoes"][0]), list(r.CAMPOS))
        self.assertIsNone(dado["execucoes"][0]["versao_agente"])

    def test_chave_repetida_nao_grava(self):
        with self.assertRaises(ValueError):
            r.gravar(self.arquivo, "linha-de-base-2", [registro(), registro()])
        self.assertFalse(self.arquivo.exists())

    def test_registro_invalido_nao_grava_e_nao_corrompe_o_anterior(self):
        r.gravar(self.arquivo, "linha-de-base-2", [registro()])
        antes = self.arquivo.read_text()
        with self.assertRaises(ValueError):
            r.gravar(self.arquivo, "linha-de-base-2", [registro(), registro(id_caso="A1-002", erro="x")])
        self.assertEqual(self.arquivo.read_text(), antes)

    def test_nao_deixa_arquivo_temporario(self):
        r.gravar(self.arquivo, "linha-de-base-2", [registro()])
        self.assertEqual([p.name for p in self.arquivo.parent.iterdir()], ["resultados-agente1.json"])

    def test_repeticoes_do_mesmo_caso_tem_chaves_diferentes(self):
        r.gravar(self.arquivo, "linha-de-base-2", [registro(repeticao=1), registro(repeticao=2)])


if __name__ == "__main__":
    unittest.main()
