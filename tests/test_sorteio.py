"""Testes do sorteio dos casos do agente único (T49, D97). Sem LLM e sem Maven."""
import unittest

from agente_contrato.sorteio import CATEGORIAS, ROTULOS, ids_sorteados, sortear


def _casos(por_combinacao: int = 2) -> list[dict]:
    casos, n = [], 0
    for categoria in CATEGORIAS:
        for rotulo in ROTULOS:
            for _ in range(por_combinacao):
                n += 1
                casos.append({"id_caso": f"A1-{n:03d}", "categoria": categoria, "rotulo_oraculo": rotulo})
    return casos


class TestSortear(unittest.TestCase):
    def test_um_por_combinacao_na_ordem_fixa(self):
        s = sortear(_casos(), 7)
        self.assertEqual([(e["categoria"], e["rotulo_oraculo"]) for e in s],
                         [(c, r) for c in CATEGORIAS for r in ROTULOS])
        for e in s:
            self.assertIn(e["id_caso"], e["candidatos"])

    def test_mesma_semente_mesmo_resultado(self):
        self.assertEqual(sortear(_casos(), 4949), sortear(_casos(), 4949))

    def test_ordem_dos_casos_no_arquivo_nao_importa(self):
        casos = _casos()
        self.assertEqual(sortear(casos, 4949), sortear(list(reversed(casos)), 4949))

    def test_le_so_id_categoria_e_rotulo(self):
        casos = [{**c, "patch": None, "correcao_esperada": None} for c in _casos()]
        self.assertEqual(sortear(casos, 1), sortear(_casos(), 1))

    def test_combinacao_sem_caso_para(self):
        casos = [c for c in _casos() if not (c["categoria"] == "remocao" and c["rotulo_oraculo"] == "legitima")]
        with self.assertRaises(ValueError):
            sortear(casos, 1)

    def test_4_legitimos_e_4_regressoes(self):
        s = sortear(_casos(3), 4949)
        self.assertEqual(sum(e["rotulo_oraculo"] == "legitima" for e in s), 4)
        self.assertEqual(sum(e["rotulo_oraculo"] == "problema_real" for e in s), 4)

    def test_ids_sorteados(self):
        s = {"sorteados": [{"id_caso": "A1-020"}, {"id_caso": "A1-013"}]}
        self.assertEqual(ids_sorteados(s), {"A1-013", "A1-020"})


if __name__ == "__main__":
    unittest.main()
