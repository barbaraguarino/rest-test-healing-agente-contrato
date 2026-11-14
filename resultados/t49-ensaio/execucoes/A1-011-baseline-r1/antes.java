        @Test
        @DisplayName("Deve retornar 422 quando o SKU já estiver cadastrado")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/produto/produtos.sql"})
        void shouldReturn422WhenSkuAlreadyExists() throws Exception {
            mockMvc.perform(post("/produtos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "sku": "LIV-001",
                                      "nome": "Livro Repetido",
                                      "preco": 10.00,
                                      "categoria": "LIVROS",
                                      "ativo": true,
                                      "estoque": 1,
                                      "pesoGramas": 100,
                                      "dimensoes": {"alturaCm": 1, "larguraCm": 1, "comprimentoCm": 1}
                                    }
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));
        }