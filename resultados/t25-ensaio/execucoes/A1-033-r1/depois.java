        @Test
        @DisplayName("Deve contar o quilo iniciado quando o peso passar 1 g do quilo (RN05: 1.001 g = 2 kg; 15,00 + 2 × 2,00 = 19,00)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn05.sql"})
        void shouldCountStartedKilogramWhenWeightExceedsKilogramByOneGram() throws Exception {
            mockMvc.perform(post("/fretes/cotacao")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "destino": {"cep": "01001000", "uf": "SP"},
                                      "modalidade": "PADRAO",
                                      "seguro": false,
                                      "itens": [{"produtoId": 2, "quantidade": 1}]
                                    }
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.valor").value(decimal("19.00")));
        }