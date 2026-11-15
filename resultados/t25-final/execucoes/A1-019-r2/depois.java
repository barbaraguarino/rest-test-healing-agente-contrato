        @Test
        @DisplayName("Deve dar frete grátis, com valor 0,00 e prazo inalterado, quando o subtotal estiver no limite na PADRAO (RN07)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn07.sql"})
        void shouldGiveFreeShippingWhenSubtotalIsAtThreshold() throws Exception {
            mockMvc.perform(post("/fretes/cotacao")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "destino": {"cep": "01001000", "uf": "SP"},
                                      "modalidade": "PADRAO",
                                      "itens": [{"produtoId": 1, "quantidade": 1}]
                                    }
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.valor").value(decimal("0.00")))
                    .andExpect(jsonPath("$.prazoDias").value(is(3)));
        }