        @Test
        @DisplayName("Deve retornar 200 OK com o item e os subtotais quando o produto estiver disponível (2 × 25,50 = 51,00)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/carrinho/carrinhos.sql"})
        void shouldReturn200WithItemAndSubtotalsWhenProductIsAvailable() throws Exception {
            mockMvc.perform(post("/carrinhos/101/itens")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"produtoId": 1, "quantidade": 2}
                                    """))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value(is(101)))
                    .andExpect(jsonPath("$.itens").value(hasSize(1)))
                    .andExpect(jsonPath("$.itens[0].produtoId").value(is(1)))
                    .andExpect(jsonPath("$.itens[0].quantidade").value(is(2)))
                    .andExpect(jsonPath("$.itens[0].precoUnitario").value(decimal("25.50")))
                    .andExpect(jsonPath("$.itens[0].subtotal").value(decimal("51.00")))
                    .andExpect(jsonPath("$.subtotal").value(decimal("51.00")));
        }