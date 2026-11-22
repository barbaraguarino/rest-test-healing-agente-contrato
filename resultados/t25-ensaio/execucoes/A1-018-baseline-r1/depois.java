        @Test
        @DisplayName("Deve retornar 422 quando o subtotal estiver um centavo abaixo do mínimo do cupom (RN08)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn08.sql"})
        void shouldReturn422WhenSubtotalIsOneCentBelowCouponMinimum() throws Exception {
            mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 102,
                                      "cliente": {"nomeCompleto": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO",
                                      "cupom": "BEMVINDO10"
                                    }
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));
        }