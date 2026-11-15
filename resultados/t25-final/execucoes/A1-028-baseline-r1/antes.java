        @Test
        @DisplayName("Deve retornar 404 Not Found quando o carrinho não existir")
        @Sql("/fixtures/limpeza.sql")
        void shouldReturn404WhenCartDoesNotExist() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 999,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO"
                                    }
                                    """))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.codigo").value("RECURSO_NAO_ENCONTRADO"));
        }