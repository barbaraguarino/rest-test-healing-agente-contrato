        @Test
        @DisplayName("Deve dar frete grátis pelo subtotal antes do desconto quando o subtotal estiver no limite (RN07)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn07.sql"})
        void shouldGiveFreeShippingUsingSubtotalBeforeDiscount() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 101,
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
                    .andExpect(jsonPath("$.frete").value(decimal("0.00")));
        }