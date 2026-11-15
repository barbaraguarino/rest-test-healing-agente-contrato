        @Test
        @DisplayName("Deve retornar 200 OK com status CANCELADO e devolver o estoque quando o pedido aguardar pagamento (RN11: 3 + 2 = 5)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn11.sql"})
        void shouldReturn200AndReturnStockWhenOrderIsAwaitingPayment() throws Exception {
            mockMvc.perform(post("/pedidos/301/cancelamento"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value(is(301)))
                    .andExpect(jsonPath("$.status").value("CANCELADO"));

            mockMvc.perform(get("/produtos/1"))
                    .andExpect(jsonPath("$.estoque").value(is(5)));
        }