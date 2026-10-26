# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (`rest-test-healing-sut`) e não repara quando a quebra é uma regressão do código.

## Estado

A versão agêntica (Classifier e Repair em laço com ferramentas, D62) está sendo escrita do zero na branch `develop` (tarefa T23). Este README cresce junto com o código e, no fim, é o guia completo de reprodução.

A versão apresentada na Rodada 2 (baseline determinística e v1 com pipeline fixo Classifier → Repair) está preservada na tag **`rodada-2`** (commit `263862a`), com o código, os testes, os prompts e o README de execução da época.

## Regenerar os resultados do piloto

Os resultados do piloto só se regeneram com o código da tag `rodada-2`: o código novo segue regras decididas depois do piloto (D114 a D116) e daria outro resultado em pelo menos um caso.

1. No PyCharm, abra a janela **Git**, aba **Log**.
2. Clique com o botão direito na tag `rodada-2` e escolha **Checkout**.
3. Siga o README que aparece nesse ponto.
4. Para voltar ao desenvolvimento, faça checkout da branch `develop`.

## Casos e oráculo

`casos/` guarda os 12 casos do piloto, congelados na tag `oraculo-piloto`:

| Arquivo | Conteúdo |
|---|---|
| `casos/A1-NNN.patch` | A mudança do caso: código em `src/` e o `docs/openapi.json` novo, aplicados sobre a tag `linha-de-base-2` da API cobaia |
| `casos/A1-NNN.esperado.patch` | A correção esperada do teste afetado, só nos casos de mudança legítima |
| `casos/oraculo-agente1.json` | Rótulo, categoria, lado, teste afetado e correção esperada de cada caso |

O agente nunca lê o oráculo. Ele recebe só o patch aplicado na API cobaia e o nome do teste afetado; o rótulo é copiado para o resultado depois da execução.

## Resultados guardados

| Pasta | Conteúdo |
|---|---|
| `resultados/piloto/` | Baseline nos 12 casos do piloto, 3 repetições (T08) |
| `resultados/t42-baseline/` | Baseline com os limites de tempo da D111 (T42) e métricas antes e depois da D113 |
| `resultados/t42-etapa0/` | Ensaio da v1 com o Maven de verdade e LLM simulado (T42) |
| `resultados/t09-*` | Ensaio da v1 em 4 casos, com a API paga (T09); não são resultados do estudo |
| `resultados/t10-piloto/` | Piloto da v1 nos 12 casos, 3 repetições (T10), e métricas antes e depois da D113 |
| `resultados/t44-d113/` | Conferência do defeito da correção esperada do A1-007 (T44) |

Os detalhes de cada rodada estão no README da tag `rodada-2` e na Operação do Estudo (repositório `rest-test-healing-estudo`).

## Licença

MIT. Ver `LICENSE`.
