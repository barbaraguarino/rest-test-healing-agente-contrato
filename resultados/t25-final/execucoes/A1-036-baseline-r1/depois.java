        @Test
        @DisplayName("Deve retornar 201 Created com descricao nula e tags vazia quando os campos opcionais não forem enviados")
        @Sql("/fixtures/limpeza.sql")
        void shouldReturn201WithNullDescriptionAndEmptyTagsWhenOptionalFieldsAreMissing() throws Exception {
            mockMvc.perform(post("/produtos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "sku": "VES-001",
                                      "nome": "Camiseta",
                                      "preco": 49.90,
                                      "categoria": "VESTUARIO",
                                      "ativo": false,
                                      "estoque": 0,
                                      "pesoGramas": 200,
                                      "dimensoes": {"alturaCm": 2, "larguraCm": 30, "comprimentoCm": 40}
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.descricao").value(nullValue()))
                    .andExpect(jsonPath("$.tags").value(empty()))
                    .andExpect(jsonPath("$.ativo").value(false))
                    .andExpect(jsonPath("$.quantidadeEstoque").value(is(0)));
        }