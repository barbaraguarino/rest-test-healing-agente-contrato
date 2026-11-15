        @Test
        @DisplayName("Deve retornar todos os produtos, inclusive os inativos, ordenados por SKU, quando a categoria não for informada")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/produto/produtos.sql"})
        void shouldReturnAllProductsIncludingInactiveWhenCategoryIsMissing() throws Exception {
            mockMvc.perform(get("/produtos"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$[*].sku").value(contains("CAS-001", "LIV-001", "LIV-002")))
                    .andExpect(jsonPath("$[*].ativo").value(contains(true, false, true)));
        }