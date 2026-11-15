        @Test
        @DisplayName("Deve retornar 201 Created, o cabeçalho Location e todos os campos quando o pedido tiver cupom e complemento (1.400 g = 2 kg; 150,00 − 15,00 + 19,00 = 154,00)")
        @Sql({"/fixtures/limpeza.sql", "/fixtures/pedido/pedidos.sql"})
        void shouldReturn201WithAllFieldsWhenOrderHasCouponAndComplement() throws Exception {
            MvcResult resultado = mockMvc.perform(post("/pedidos")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("""
                                    {
                                      "carrinhoId": 101,
                                      "cliente": {"nome": "Ana Souza", "email": "ana@exemplo.com"},
                                      "enderecoEntrega": {
                                        "logradouro": "Rua A", "numero": "10", "complemento": "Apto 1",
                                        "cidade": "Campinas", "uf": "SP", "cep": "13010000"
                                      },
                                      "modalidadeFrete": "PADRAO",
                                      "cupom": "BEMVINDO10"
                                    }
                                    """))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.id").isNumber())
                    .andExpect(jsonPath("$.status").value("AGUARDANDO_PAGAMENTO"))
                    .andExpect(jsonPath("$.cliente.nome").value("Ana Souza"))
                    .andExpect(jsonPath("$.cliente.email").value("ana@exemplo.com"))
                    .andExpect(jsonPath("$.enderecoEntrega.logradouro").value("Rua A"))
                    .andExpect(jsonPath("$.enderecoEntrega.numero").value("10"))
                    .andExpect(jsonPath("$.enderecoEntrega.cidade").value("Campinas"))
                    .andExpect(jsonPath("$.enderecoEntrega.uf").value("SP"))
                    .andExpect(jsonPath("$.enderecoEntrega.cep").value("13010000"))
                    .andExpect(jsonPath("$.modalidadeFrete").value("PADRAO"))
                    .andExpect(jsonPath("$.itens").value(hasSize(2)))
                    .andExpect(jsonPath("$.itens[0].produtoId").value(is(1)))
                    .andExpect(jsonPath("$.itens[0].nomeProduto").value("Livro de Testes"))
                    .andExpect(jsonPath("$.itens[0].quantidade").value(is(2)))
                    .andExpect(jsonPath("$.itens[0].precoUnitario").value(decimal("50.00")))
                    .andExpect(jsonPath("$.itens[0].subtotal").value(decimal("100.00")))
                    .andExpect(jsonPath("$.itens[1].produtoId").value(is(2)))
                    .andExpect(jsonPath("$.itens[1].nomeProduto").value("Caneca"))
                    .andExpect(jsonPath("$.itens[1].quantidade").value(is(2)))
                    .andExpect(jsonPath("$.itens[1].precoUnitario").value(decimal("25.00")))
                    .andExpect(jsonPath("$.itens[1].subtotal").value(decimal("50.00")))
                    .andExpect(jsonPath("$.subtotal").value(decimal("150.00")))
                    .andExpect(jsonPath("$.desconto").value(decimal("15.00")))
                    .andExpect(jsonPath("$.frete").value(decimal("19.00")))
                    .andExpect(jsonPath("$.total").value(decimal("154.00")))
                    .andReturn();

            assertThat(resultado.getResponse().getHeader("Location"), is("/pedidos/" + lerId(resultado)));
        }