        @Test
        @DisplayName("Deve retornar 201 Created, o cabeçalho Location e todos os campos quando o corpo estiver completo")
        @Sql("/fixtures/limpeza.sql")
        void shouldReturn201WithAllFieldsWhenPayloadIsComplete() throws Exception {
            MvcResult resultado = mockMvc.perform(post("/produtos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "sku": "ELE-001",
                                      "nome": "Fone de Ouvido",
                                      "descricao": "Fone sem fio",
                                      "preco": 199.90,
                                      "categoria": "ELETRONICOS",
                                      "ativo": true,
                                      "estoque": 15,
                                      "pesoGramas": 250,
                                      "dimensoes": {"alturaCm": 18, "larguraCm": 16, "comprimentoCm": 8},
                                      "tags": ["promo", "novo"]
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.id").isNumber())
                    .andExpect(jsonPath("$.sku").value("ELE-001"))
                    .andExpect(jsonPath("$.titulo").value("Fone de Ouvido"))
                    .andExpect(jsonPath("$.descricao").value("Fone sem fio"))
                    .andExpect(jsonPath("$.preco").value(decimal("199.90")))
                    .andExpect(jsonPath("$.categoria").value("ELETRONICOS"))
                    .andExpect(jsonPath("$.ativo").value(true))
                    .andExpect(jsonPath("$.estoque").value(is(15)))
                    .andExpect(jsonPath("$.pesoGramas").value(is(250)))
                    .andExpect(jsonPath("$.dimensoes.alturaCm").value(is(18)))
                    .andExpect(jsonPath("$.dimensoes.larguraCm").value(is(16)))
                    .andExpect(jsonPath("$.dimensoes.comprimentoCm").value(is(8)))
                    .andExpect(jsonPath("$.tags").value(contains("promo", "novo")))
                    .andReturn();

            assertThat(resultado.getResponse().getHeader("Location"), is("/produtos/" + lerId(resultado)));
        }