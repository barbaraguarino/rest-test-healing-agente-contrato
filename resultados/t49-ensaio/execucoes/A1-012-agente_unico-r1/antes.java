        @Test
        @DisplayName("Deve retornar 201 Created com desconto 0,00 e complemento nulo quando os campos opcionais não forem enviados (50,00 + 17,00 = 67,00)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/pedido/pedidos.sql"})
        void shouldReturn201WithZeroDiscountWhenOptionalFieldsAreMissing() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 102,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO"
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.enderecoEntrega.complemento").value(nullValue()))
                    .andExpect(jsonPath("$.subtotal").value(decimal("50.00")))
                    .andExpect(jsonPath("$.desconto").value(decimal("0.00")))
                    .andExpect(jsonPath("$.frete").value(decimal("17.00")))
                    .andExpect(jsonPath("$.total").value(decimal("67.00")));
        }