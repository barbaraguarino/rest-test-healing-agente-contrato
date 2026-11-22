        @Test
        @DisplayName("Deve retornar 422 quando o carrinho estiver vazio (RN10)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/pedido/pedidos.sql"})
        void shouldReturn422WhenCartIsEmpty() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 104,
                                      "cliente": {"nome": "Ana Souza", "emailContato": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO"
                                    }
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));
        }