        @Test
        @DisplayName("Deve retornar 422 quando o cupom não existir, com subtotal acima do mínimo (RN08)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn08.sql"})
        void shouldReturn422WhenCouponDoesNotExist() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "idCarrinho": 101,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO",
                                      "cupom": "NAOEXISTE"
                                    }
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));
        }