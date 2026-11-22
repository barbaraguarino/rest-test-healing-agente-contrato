        @Test
        @DisplayName("Deve aceitar o cupom quando o subtotal estiver no mínimo do cupom (RN08)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn08.sql"})
        void shouldAcceptCouponWhenSubtotalIsAtMinimum() throws Exception {
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
                    .andExpect(status().isCreated());
        }