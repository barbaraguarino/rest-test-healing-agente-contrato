        @Test
        @DisplayName("Deve retornar 200 OK quando o carrinho estiver uma unidade abaixo do máximo por produto (RN02)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn02.sql"})
        void shouldReturn200WhenCartIsOneUnitBelowMaximum() throws Exception {
            mockMvc.perform(post("/carrinhos/101/itens")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"produtoId": 1, "quantidade": 1}
                                    """))
                    .andExpect(status().isOk());
        }