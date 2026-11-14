        @Test
        @DisplayName("Deve baixar o estoque quando o pedido for criado (RN03: 5 − 2 = 3)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn03.sql"})
        void shouldDecreaseStockWhenOrderIsCreated() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 103,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com", "cpf": "texto"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO"
                                    }
                                    """))
                    .andExpect(status().isCreated());

            mockMvc.perform(get("/produtos/2"))
                    .andExpect(jsonPath("$.estoque").value(is(3)));
        }