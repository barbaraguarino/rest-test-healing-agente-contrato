# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (`rest-test-healing-sut`) e não repara quando a quebra é uma regressão do código.

Hoje o repositório tem só os casos do piloto e o oráculo deles. O código da baseline determinística e do agente entra nas próximas tarefas.

## Casos do piloto

Cada caso é uma mudança aplicada sobre a tag `linha-de-base-2` da API cobaia que quebra um teste da suíte. O teste que o caso avalia é o de `teste_afetado`; outros testes podem quebrar com a mesma mudança, mas não contam para o caso.

| Arquivo | Conteúdo |
|---|---|
| `casos/A1-NNN.patch` | A mudança do caso: código em `src/` e o `docs/openapi.json` regenerado pelo springdoc |
| `casos/A1-NNN.esperado.patch` | A correção esperada do teste afetado, aplicada depois do patch do caso; só nos casos de mudança legítima |
| `casos/oraculo-agente1.json` | Oráculo: rótulo e correção esperada de cada caso |

Composição: 12 casos, três por categoria (renomeação, remoção e alteração de tipo de campo, e campo obrigatório novo), com duas mudanças legítimas e uma regressão em cada categoria.

Numa **mudança legítima**, o código e o contrato mudam juntos, e o reparo correto é atualizar o teste. Numa **regressão**, o contrato registra só uma parte da mudança (P1), e o código quebra outro ponto que o contrato não registra (P2), no mesmo teste; o reparo correto é não alterar o teste.

### Oráculo

`casos/oraculo-agente1.json` é um objeto com `versao_api` (a tag da API cobaia) e `casos`, a lista de casos com os campos:

| Campo | Valores |
|---|---|
| `id_caso` | `A1-001` a `A1-012` |
| `categoria` | `renomeacao`, `remocao`, `alteracao_tipo`, `campo_obrigatorio_novo` |
| `lado` | `requisicao`, `resposta` |
| `teste_afetado` | `ClasseDeTeste.metodo` |
| `patch` | caminho do patch do caso |
| `rotulo_oraculo` | `legitima`, `problema_real` |
| `correcao_esperada` | caminho do patch da correção esperada; `null` na regressão |

**O oráculo nunca é enviado ao agente.** O rótulo é copiado para o arquivo de resultados pelo código, depois da execução.

### Como aplicar um caso

```bash
git -C rest-test-healing-sut checkout linha-de-base-2
git -C rest-test-healing-sut apply ../rest-test-healing-agente-contrato/casos/A1-001.patch
```

Para ver a correção esperada, aplique em seguida `casos/A1-001.esperado.patch`. Para voltar ao estado da tag: `git -C rest-test-healing-sut checkout -- . && git -C rest-test-healing-sut clean -fd`.

### Conferência

Em 20/10/2026, com Java 21 e o Maven Wrapper da API cobaia, cada caso foi conferido sobre a `linha-de-base-2`, cuja suíte passa nas 65 execuções:

- o teste afetado falha com o patch do caso;
- nos casos de mudança legítima, ele volta a passar com a correção esperada;
- nas regressões, ele continua falhando quando só a parte registrada no contrato (P1) é corrigida no teste.

### Congelamento

Os casos e o oráculo do piloto são congelados na tag `oraculo-piloto`, criada depois do merge e antes de qualquer execução. Depois da tag, nenhum arquivo de `casos/` é alterado sem registro como desvio na Operação do Estudo. Os casos da execução final são outros e serão congelados na tag `oraculo-final`.

## Licença

MIT. Ver `LICENSE`.
