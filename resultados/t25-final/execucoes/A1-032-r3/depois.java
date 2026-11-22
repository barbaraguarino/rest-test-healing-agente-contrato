        @Test
        @DisplayName("Deve arredondar o preço 10,005 para 10,01 com HALF_UP (RN09; HALF_EVEN daria 10,00)")
        @Sql("/fixtures/limpeza.sql")
        void shouldRoundPriceHalfUpWhenPriceHasThreeDecimalPlaces() throws Exception {
            mockMvc.perform(post("/produtos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "sku": "CAS-002",
                                      "nome": "Pano de Prato",
                                      "preco": 10.005,
                                      "categoria": "CASA",
                                      "ativo": true,
                                      "estoque": 3,
                                      "pesoGramas": 80,
                                      "garantiaMeses": 12,
                                      "dimensoes": {"alturaCm": 1, "larguraCm": 40, "comprimentoCm": 60}
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.preco").value(decimal("10.01")));
        }