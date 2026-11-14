        @Test
        @DisplayName("Deve retornar 200 OK com todos os campos e as tags na ordem de cadastro quando o produto existir")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/produto/produtos.sql"})
        void shouldReturn200WithAllFieldsWhenProductExists() throws Exception {
            mockMvc.perform(get("/produtos/1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value(is(1)))
                    .andExpect(jsonPath("$.sku").value("LIV-002"))
                    .andExpect(jsonPath("$.nome").value("Livro de Java"))
                    .andExpect(jsonPath("$.descricao").value("Livro sobre Java"))
                    .andExpect(jsonPath("$.preco").value(decimal("89.90")))
                    .andExpect(jsonPath("$.categoria").value("LIVROS"))
                    .andExpect(jsonPath("$.ativo").value(true))
                    .andExpect(jsonPath("$.estoque").value(is(7)))
                    .andExpect(jsonPath("$.pesoGramas").value(is(600)))
                    .andExpect(jsonPath("$.dimensoes.alturaCm").value(is(23)))
                    .andExpect(jsonPath("$.dimensoes.larguraCm").value(is(16)))
                    .andExpect(jsonPath("$.dimensoes.comprimentoCm").value(is(3)))
                    .andExpect(jsonPath("$.tags").value(contains("programacao", "java")));
        }