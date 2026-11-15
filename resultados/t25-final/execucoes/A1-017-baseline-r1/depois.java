        @Test
        @DisplayName("Deve arredondar o desconto com HALF_UP (RN09: 10% de 100,05 = 10,005 → 10,01, HALF_EVEN daria 10,00; 100,05 − 10,01 + 17,00 = 107,04)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/pedido/pedidos.sql"})
        void shouldRoundDiscountHalfUp() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 103,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO",
                                      "cupom": "BEMVINDO10"
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.valorDesconto").value(decimal("10.01")))
                    .andExpect(jsonPath("$.total").value(decimal("107.04")));
        }