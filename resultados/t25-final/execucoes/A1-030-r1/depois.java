        @Test
        @DisplayName("Deve contar 1 kg quando o peso for exatamente 1.000 g (RN05: 15,00 + 1 × 2,00 = 17,00)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn05.sql"})
        void shouldCountOneKilogramWhenWeightIsExactlyOneKilogram() throws Exception {
            mockMvc.perform(post("/fretes/cotacao")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "destino": {"codigoPostal": "01001000", "uf": "SP"},
                                      "modalidade": "PADRAO",
                                      "itens": [{"produtoId": 1, "quantidade": 1}]
                                    }
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.valor").value(decimal("17.00")));
        }