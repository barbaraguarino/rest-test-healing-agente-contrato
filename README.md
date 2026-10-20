# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (`rest-test-healing-sut`) e não repara quando a quebra é uma regressão do código.

O repositório tem os casos do piloto com o oráculo deles e a baseline determinística do Agente 1 (D75), sem LLM. O agente com LLM entra na T09.

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

## Baseline determinística

Lê a diferença entre o contrato OpenAPI antigo e o novo e aplica cada mudança mecanicamente no método de teste afetado: renomeia o campo, retira o campo removido, converte o valor para o tipo novo e acrescenta o campo obrigatório novo com um valor padrão por tipo. Se a diferença não atinge o teste, não repara. Não chama LLM nem API paga.

Python 3.13 com a biblioteca padrão (sem dependências); a API cobaia precisa de Java 21 e do Maven Wrapper dela.

| Módulo | Responsabilidade |
|---|---|
| `agente_contrato/contrato.py` | diferença entre dois `openapi.json`, por operação e lado (requisição/resposta 2xx) |
| `agente_contrato/teste_java.py` | leitura do método de teste: chamadas, corpo JSON com posições, asserções `jsonPath` |
| `agente_contrato/baseline.py` | as regras da D75: mudança de contrato → edição do teste |
| `agente_contrato/guarda.py` | recusa reparo que remove teste, acrescenta `@Disabled`, tira asserção ou afrouxa matcher (exceção da D77) |
| `agente_contrato/comparador.py` | equivalência com a correção esperada (regras 1 a 3 da D95) e troca de cenário |
| `agente_contrato/execucao.py` | cópia limpa da tag, patch do caso e execução de um único teste pelo Maven |
| `agente_contrato/resultados.py` | validação e gravação atômica do arquivo de resultados (D74) |
| `agente_contrato/rodar_baseline.py` | junta tudo e roda os casos |

`contrato.py`, `teste_java.py`, `guarda.py`, `execucao.py` e `resultados.py` são reaproveitados pelo agente com LLM; só `baseline.py` é específico da baseline.

### Como rodar

Na raiz do repositório, com a API cobaia clonada ao lado:

```bash
python3 -m agente_contrato.rodar_baseline --api ../rest-test-healing-sut --saida resultados-baseline --repeticoes 3
```

Grava `resultados-agente1.json`, no formato da D74, e `log-baseline.json`, com o que não cabe no formato: tempos do Maven e do teste, mudanças aplicadas e ignoradas, motivos da comparação, casos para revisão manual e se as repetições deram o mesmo resultado. O rótulo e a correção esperada do oráculo só são lidos depois da execução de cada caso.

Testes da própria baseline (não precisam do Maven):

```bash
python3 -I -m unittest discover -s tests -t .
```

### Limites conhecidos

- Só o corpo da requisição e das respostas 2xx entram na diferença; parâmetros de caminho e de consulta não.
- Renomeação é um campo removido e um adicionado no mesmo objeto, com o mesmo tipo e enum; havendo mais de um candidato, não se adivinha.
- Só edita corpos em text block (`"""`) e asserções `.value(...)` simples; matchers como `hasSize(...)` não são convertidos.
- O guarda conta asserções; trocar uma por outra do mesmo número é assunto do comparador.
- O resultado de um teste só vale se o Surefire executou exatamente um teste: o Maven responde `BUILD SUCCESS` com `Tests run: 0` quando o filtro não casa.

## Licença

MIT. Ver `LICENSE`.
