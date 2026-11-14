        @Test
        @DisplayName("Deve retornar 200 OK com todos os campos quando a cotação for válida (PADRAO para SP, 500 g: 15,00 + 1 × 2,00 = 17,00, prazo 3)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/frete/frete.sql"})
        void shouldReturn200WithAllFieldsWhenQuotationIsValid() throws Exception {
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
                    .andExpect(jsonPath("$.modalidade").value("PADRAO"))
                    .andExpect(jsonPath("$.valor").value(decimal("17.00")))
                    .andExpect(jsonPath("$.prazoDias").value(is(3)))
                    .andExpect(jsonPath("$.freteGratis").value(false))
                    .andExpect(jsonPath("$.pesoTotalGramas").value(is(500)));
        }