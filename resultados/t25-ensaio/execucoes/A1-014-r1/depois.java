        @Test
        @DisplayName("Deve retornar prazo de 1 dia, o mínimo, na EXPRESSA para o Sudeste (RN06: (15,00 + 2,00) × 1,5 = 25,50; prazo 3 − 2 = 1)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/frete/frete.sql"})
        void shouldReturnOneDayDeadlineWhenModeIsExpressInSoutheast() throws Exception {
            mockMvc.perform(post("/fretes/cotacao")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "destino": {"cep": "01001000", "uf": "SP"},
                                      "modalidade": "EXPRESSA",
                                      "itens": [{"produtoId": 1, "quantidade": 1}]
                                    }
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.valor").value(decimal("25.50")))
                    .andExpect(jsonPath("$.prazoEntregaDias").value(is(1)));
        }