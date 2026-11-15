        @Test
        @DisplayName("Deve retornar 422 quando o produto estiver inativo (RN01)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/regras/rn01.sql"})
        void shouldReturn422WhenProductIsInactive() throws Exception {
            mockMvc.perform(post("/carrinhos/101/itens")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {"produtoId": 1, "quantidade": 1, "origem": "SITE"}
                                    """))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.codigo").value("REGRA_DE_NEGOCIO"))
                    .andExpect(jsonPath("$.campos").value(empty()));
        }