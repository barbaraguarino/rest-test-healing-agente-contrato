        @Test
        @DisplayName("Deve somar a quantidade no item existente, que mantém a posição, quando o produto já estiver no carrinho (3 × 30,00 + 3 × 25,50 = 166,50)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/carrinho/carrinhos.sql"})
        void shouldAddQuantityToExistingItemWhenProductIsAlreadyInCart() throws Exception {
            mockMvc.perform(post("/carrinhos/102/itens")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"produtoId": 2, "quantidade": 2}
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.itens[*].produtoId").value(contains(2, 1)))
                    .andExpect(jsonPath("$.itens[*].quantidade").value(contains(3, 3)))
                    .andExpect(jsonPath("$.subtotal").value(decimal("166.50")));
        }