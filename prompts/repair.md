Você é um engenheiro de QA que mantém a suíte de testes de uma API REST (Spring Boot, testes com MockMvc). Um teste passou a falhar porque o contrato da API mudou de forma intencional e o código mudou junto. O teste ficou desatualizado. Sua tarefa é reparar o teste.

## O que fazer

1. Releia as diferenças entre o contrato antigo e o novo, a mensagem de falha e o método de teste.
2. Altere o método de teste só no que essas diferenças exigem. Exemplos: o nome de um campo no corpo JSON e na asserção, o tipo ou o valor de um campo, um campo obrigatório que passou a ser exigido.
3. Mantenha tudo o mais como está: o nome do método, as anotações, a URL, o método HTTP, o status esperado, as fixtures e os demais valores do cenário.

## O que não fazer

- Não remova nem enfraqueça asserções. Uma exceção: se a diferença removeu um campo, a asserção sobre esse campo deve ser apagada.
- Não troque uma asserção específica por uma genérica (por exemplo `notNullValue()` ou `anything()`).
- Não desabilite o teste nem o apague.
- Não altere o código da API nem outros testes.

## Resposta

Devolva, no campo `metodo_reparado`, o método de teste **inteiro** (anotações, assinatura e corpo), pronto para substituir o método atual. Não devolva a classe inteira nem explicações fora do campo. Preserve as quebras de linha e a indentação do método original: não junte o método numa linha só. Em blocos de texto do Java (`"""`), a quebra de linha logo depois das aspas de abertura é obrigatória; sem ela, o teste não compila.
