        @Test
        @DisplayName("Deve retornar 422 e manter estoque e carrinho quando o estoque não for mais suficiente (RN03: 3 unidades, estoque 2)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn03.sql"})
        void shouldReturn422AndKeepStockAndCartWhenStockIsNoLongerEnough() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 104,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000", "bairro": "Centro"
                                      },
                                      "modalidadeFrete": "PADRAO"
                                    }
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));

            mockMvc.perform(get("/produtos/3"))
                    .andExpect(jsonPath("$.estoque").value(is(2)));
            mockMvc.perform(get("/carrinhos/104"))
                    .andExpect(jsonPath("$.itens[*].quantidade").value(contains(3)));
        }