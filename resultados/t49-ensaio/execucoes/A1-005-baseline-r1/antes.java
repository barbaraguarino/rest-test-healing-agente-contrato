        @Test
        @DisplayName("Deve multiplicar o valor e reduzir o prazo na EXPRESSA (RN06, AM com 1.800 g: (30,00 + 2 × 2,00) × 1,5 = 51,00; prazo 8 − 2 = 6)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/frete/frete.sql"})
        void shouldMultiplyValueAndReduceDeadlineWhenModeIsExpress() throws Exception {
            mockMvc.perform(post("/fretes/cotacao")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "destino": {"cep": "69005000", "uf": "AM"},
                                      "modalidade": "EXPRESSA",
                                      "itens": [{"produtoId": 2, "quantidade": 1}]
                                    }
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.modalidade").value("EXPRESSA"))
                    .andExpect(jsonPath("$.valor").value(decimal("51.00")))
                    .andExpect(jsonPath("$.prazoDias").value(is(6)))
                    .andExpect(jsonPath("$.freteGratis").value(false))
                    .andExpect(jsonPath("$.pesoTotalGramas").value(is(1800)));
        }