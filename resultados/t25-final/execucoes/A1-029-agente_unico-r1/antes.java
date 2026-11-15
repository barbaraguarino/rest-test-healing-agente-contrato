        @Test
        @DisplayName("Deve cobrar o frete na EXPRESSA mesmo com o subtotal no limite (RN07: (15,00 + 2,00) × 1,5 = 25,50)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn07.sql"})
        void shouldChargeShippingWhenModeIsExpressEvenAtThreshold() throws Exception {
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
                    .andExpect(jsonPath("$.freteGratis").value(false))
                    .andExpect(jsonPath("$.valor").value(decimal("25.50")));
        }