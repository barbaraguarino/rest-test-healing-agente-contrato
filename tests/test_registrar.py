import unittest

from agente_contrato.registro import CAMPOS, Fim, registrar

LEGITIMO = {"id_caso": "A1-001", "categoria": "renomeacao", "rotulo_oraculo": "legitima"}
REGRESSAO = {"id_caso": "A1-003", "categoria": "renomeacao", "rotulo_oraculo": "problema_real"}

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
