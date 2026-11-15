        @Test
        @DisplayName("Deve retornar 201 Created com o carrinho vazio e subtotal 0,00")
        @Sql("/fixtures/limpeza.sql")
        void shouldReturn201WithEmptyCartWhenCartIsCreated() throws Exception {
            mockMvc.perform(post("/carrinhos"))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.id").isNumber())
                    .andExpect(jsonPath("$.itens").value(empty()));
        }