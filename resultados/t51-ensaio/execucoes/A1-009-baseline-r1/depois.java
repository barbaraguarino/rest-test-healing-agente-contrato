        @Test
        @DisplayName("Deve retornar 200 OK com os itens na ordem de inclusão quando o carrinho existir (30,00 + 3 × 25,50 = 106,50)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/carrinho/carrinhos.sql"})
        void shouldReturn200WithItemsInInclusionOrderWhenCartExists() throws Exception {
            mockMvc.perform(get("/carrinhos/102"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value(is(102)))
                    .andExpect(jsonPath("$.itens[0].produtoId").value(is(2)))
                    .andExpect(jsonPath("$.itens[0].quantidade").value(is(1)))
                    .andExpect(jsonPath("$.itens[0].preco").value(decimal("30.00")))
                    .andExpect(jsonPath("$.itens[0].subtotal").value(decimal("30.00")))
                    .andExpect(jsonPath("$.itens[1].produtoId").value(is(1)))
                    .andExpect(jsonPath("$.itens[1].quantidade").value(is(3)))
                    .andExpect(jsonPath("$.itens[1].preco").value(decimal("25.50")))
                    .andExpect(jsonPath("$.itens[1].subtotal").value(decimal("76.50")))
                    .andExpect(jsonPath("$.subtotal").value(decimal("106.50")));
        }