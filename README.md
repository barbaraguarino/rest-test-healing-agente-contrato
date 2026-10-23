# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (`rest-test-healing-sut`) e não repara quando a quebra é uma regressão do código.

O repositório tem os casos do piloto com o oráculo deles, a baseline determinística do Agente 1 (D75), sem LLM, e a v1 com LLM (Classifier + Repair em pipeline fixo, T09).

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

Python 3.13 (nuvem) e 3.14 (IntelliJ) com a biblioteca padrão (a baseline não tem dependências); a API cobaia precisa de Java 21 e do Maven Wrapper dela.

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

`contrato.py`, `teste_java.py`, `guarda.py`, `execucao.py` e `resultados.py` são reaproveitados pelo agente com LLM; só `baseline.py` é específico da baseline. A `rotas_do_contrato` mora em `contrato.py`, com um atalho em `baseline.py` (D103).

### Como rodar

Na raiz do repositório, com a API cobaia clonada ao lado:

```bash
python3 -m agente_contrato.rodar_baseline --api ../rest-test-healing-sut --saida resultados-baseline --repeticoes 3
```

Grava `resultados-agente1.json`, no formato da D74, e `log-baseline.json`, com o que não cabe no formato: tempos do Maven e do teste, mudanças aplicadas e ignoradas, motivos da comparação, casos para revisão manual e se as repetições deram o mesmo resultado. O rótulo e a correção esperada do oráculo só são lidos depois da execução de cada caso.

Os resultados da baseline nos 12 casos do piloto (3 repetições, rodadas em 20/10/2026 pelo commit `dbc9734`) estão em `resultados/piloto/`.

Testes (não precisam do Maven nem da rede; a partir da v1 precisam do SDK instalado, ver abaixo):

```bash
python3 -I -m unittest discover -s tests -t .
```

### Limites conhecidos

- Só o corpo da requisição e das respostas 2xx entram na diferença; parâmetros de caminho e de consulta não.
- Renomeação é um campo removido e um adicionado no mesmo objeto, com o mesmo tipo e enum; havendo mais de um candidato, não se adivinha.
- Só edita corpos em text block (`"""`) e asserções `.value(...)` simples; matchers como `hasSize(...)` não são convertidos.
- O guarda conta asserções; trocar uma por outra do mesmo número é assunto do comparador.
- O resultado de um teste só vale se o Surefire executou exatamente um teste: o Maven responde `BUILD SUCCESS` com `Tests run: 0` quando o filtro não casa.

## Agente 1 v1 (Classifier + Repair)

Pipeline fixo (D58, D62): o código monta a evidência, o **Classifier** diz se a mudança de contrato é `legitima` ou `problema_real`, e, só se for legítima, o **Repair** devolve o método de teste reparado. O LLM não roda o Maven, não lê arquivo e não grava nada; quem executa, valida, aplica e registra é o código. Decisões: D100 a D106.

| Módulo | Responsabilidade |
|---|---|
| `agente_contrato/leitura_falha.py` | mensagem de falha do teste afetado, lida do relatório do Surefire (sem stack trace) |
| `agente_contrato/evidencia.py` | texto da evidência: diferença de contrato, falha, método de teste e arquivos de `src/main` do módulo |
| `prompts/classifier.md`, `prompts/repair.md` | prompts versionados, em português e sem exemplos (D70, D100) |
| `agente_contrato/prompts.py` | carrega os prompts e devolve o commit em que estão (`+alterado` se há mudança pendente) |
| `agente_contrato/saida.py` | schemas, validação do JSON, `stop_reason`, códigos `saida_invalida` e `max_tokens`, encaixe do método |
| `agente_contrato/chamada_llm.py` | SDK oficial, parâmetros fixos da D61, tradução dos erros, leitura da chave do `.env` |
| `agente_contrato/registro_llm.py` | custo em dólares, trava de orçamento e log das chamadas em JSON Lines |
| `agente_contrato/rodar_v1.py` | runner: etapas 1 a 3 da D105, reexecução por erro de rede, parada após erros seguidos |

### Instalação e chave da API

```bash
pip install -r requirements.txt     # anthropic==1.17.0
cp .env.example .env                # e preencha ANTHROPIC_API_KEY no .env
```

O `.env` fica fora do Git (`.gitignore`). A chave só é lida desse arquivo; nunca vai para log, resultado ou PR.

### Escada de execução (D105)

Cada etapa é uma execução separada, com `--saida` própria. As etapas 2 e 3 chamam a API **paga**: pedem a confirmação `SIM` e exigem `--orcamento-usd`, e a rodada para ao chegar nele.

```bash
python3 -m agente_contrato.rodar_v1 --etapa 1 --api ../rest-test-healing-sut --saida resultados/t09-etapa1
python3 -m agente_contrato.rodar_v1 --etapa 2 --api ../rest-test-healing-sut --saida resultados/t09-etapa2 --orcamento-usd 0.10
python3 -m agente_contrato.rodar_v1 --etapa 3 --api ../rest-test-healing-sut --saida resultados/t09-etapa3 --orcamento-usd 0.10
```

| Etapa | O que faz | Custo |
|---|---|---|
| 1 | conta os tokens de entrada dos prompts reais dos 4 casos da etapa 3 (roda o Maven para obter a falha; não chama o modelo) e grava `contagem-de-tokens.json` | gratuito |
| 2 | uma chamada real do Classifier no A1-001 e mostra `stop_reason`, `usage`, `thinking_tokens`, `request_id` e a validação | cerca de US$ 0,001 |
| 3 | A1-001, A1-004, A1-010 e A1-003, 1 repetição, pipeline completo | cerca de US$ 0,008 (medido em três rodadas; a estimativa da D105 era US$ 0,014) |

O piloto completo (12 casos, 3 repetições) é a T10 e não roda por este comando.

### Saídas

| Arquivo | Conteúdo |
|---|---|
| `contagem-de-tokens.json` | só na etapa 1: tokens de entrada contados por caso e prompt, caracteres, commit dos prompts e data |
| `resultados-agente1.json` | formato da D74 (`tratamento` `agentes`, `versao_agente` `v1`), com `tokens` e `custo_usd` por caso. Caso que vai para revisão manual (D80, D109) sai com `equivalente_oraculo` nulo até o veredito ser preenchido à mão; o script da T20a recusa o arquivo enquanto houver um nulo assim num caso legítimo reparado |
| `chamadas.jsonl` | uma linha por chamada ao LLM, gravada na hora (D106): modelo retornado, `stop_reason`, tokens, `thinking_tokens`, `custo_usd`, `request_id`, latência, commit do prompt, resposta bruta e erro |
| `log-v1.json` | resumo por caso: rótulo e justificativa do Classifier, tentativas, chamadas, guarda, durações do Maven e do teste (para a T33), commit dos prompts, commit do código (`commit_do_codigo`, último commit que mexeu em `agente_contrato/`, com `+alterado` se havia mudança pendente), revisão manual e motivos da comparação |

### Resultados da T09 (ensaio da escada da D105; não são resultados do estudo)

Quatro casos, 1 repetição, `claude-haiku-5-5`. Prompts do commit `82c4edb` nas rodadas 1 e 2 e do `51894a8` na rodada 3, que acrescenta ao prompt do Repair o pedido de preservar quebras de linha e indentação (a quebra depois de `"""` é obrigatória). Eram só para ajustar a v1 (D99). Cada pasta tem também o `terminal.txt`, a saída do console copiada do IntelliJ.

| Pasta | Conteúdo | Código |
|---|---|---|
| `resultados/t09-etapa1/` | contagem de tokens (rodada 2; a contagem da rodada 1 só existiu no console e não foi guardada; o `terminal.txt` desta pasta não tem carimbo que diga de qual das duas rodadas é) | `84decff` |
| `resultados/t09-etapa2/`, `resultados/t09-etapa3/` | rodada 1: etapa 3 em 23/10/2026 (commitada às 08h34, horário de Brasília); a etapa 2 foi em 22/10, antes do `40fa93a` (ver a mensagem desse commit). O `resultados-agente1.json` da etapa 3 foi regravado depois com o comparador corrigido (ver abaixo) | `40fa93a` (etapa 3) |
| `resultados/t09-etapa2-r2/`, `resultados/t09-etapa3-r2/` | rodada 2, 23/10/2026 | `84decff` |
| `resultados/t09-etapa1-r3/`, `resultados/t09-etapa2-r3/`, `resultados/t09-etapa3-r3/` | rodada 3, 23/10/2026, prompts `51894a8` (o `log-v1.json` grava `commit_do_prompt` e `commit_do_codigo`) | `391fab9` |

| Caso | Rótulo do oráculo | Rodada 1 | Rodada 2 | Rodada 3 |
|---|---|---|---|---|
| A1-001 | legítima | reparou, passou, equivalente (no arquivo original, `cenario_alterado: true`, falso positivo corrigido na regravação; D109) | reparou, passou, equivalente | reparou, passou, equivalente |
| A1-004 | legítima | reparou, passou, equivalente | reparou, **não compilou** (equivalente só ignorando espaços) | reparou, passou, equivalente |
| A1-010 | legítima | reparou, passou, equivalente | reparou, passou, equivalente | reparou, passou, equivalente |
| A1-003 | problema real | não reparou | não reparou | não reparou |

Custo medido (etapas 2 e 3): US$ 0,009162 na rodada 1, US$ 0,008923 na rodada 2 e US$ 0,008762 na rodada 3, **US$ 0,026847 no total** (de US$ 2,00 do Agente 1). Latência por chamada de 1,9 a 5,5 s.

Métricas do script da T20a (`python -m avaliacao`), em 4 casos e 1 repetição: Detection Accuracy 4/4 nas três rodadas; Repair Rate 3/3, 2/3 e 3/3; Safety 1/1 nas três; Unsafe Repair Rate 0/3 nas três (rodada 1 pelo arquivo regravado).

Dois cuidados ao ler estes arquivos:

- O `resultados-agente1.json` da **rodada 1** foi gerado pelo `40fa93a`, antes da correção do comparador (`4b2c385`, D109), e saiu com `cenario_alterado: true` no A1-001, um falso positivo (o modelo devolveu o método numa linha só). Lido pelo script da T20a, esse arquivo dava Repair Rate 2/3 e Unsafe Repair Rate 1/3. Ele foi **regravado** offline, sem API e sem Maven, com o comparador atual: os reparos vêm de `chamadas.jsonl`, passam de novo pelo encaixe, pelo guarda e por `registrar`, e `compilou`, `passou`, `tempo_s`, `tokens` e `custo_usd` ficam os gravados na rodada. Só o `cenario_alterado` do A1-001 mudou (de `true` para `false`). Com o arquivo regravado, o script da T20a dá Detection Accuracy 4/4, Repair Rate 3/3, Safety 1/1 e Unsafe Repair Rate 0/3. O arquivo original está no histórico, no commit `5a0cb7b`. O `log-v1.json` da rodada 1 não foi regravado e ainda mostra o motivo da comparação antiga no A1-001. A rodada 2 já usa o comparador corrigido.
- As duas rodadas dão resultados diferentes porque o modelo não aceita `temperature`; ambas ficam registradas, e nenhuma é a "melhor".

### Quando o caso ou a rodada termina com erro

| Situação | O que acontece |
|---|---|
| Classifier diz `problema_real` | o Repair não roda; `decisao` `nao_reparar`, sem erro |
| JSON fora do schema, rótulo inválido, método que não encaixa, `refusal`, `model_context_window_exceeded` | `erro` `saida_invalida`, sem nova tentativa (D102) |
| resposta cortada por `max_tokens` | `erro` `max_tokens` |
| o guarda recusa o reparo | `erro` `guarda` |
| o reparo não compila ou o teste não passa | sem `erro`; `compilou` e `passou` dizem o que houve |
| erro de rede, 408, 409, 429 com `retry-after`, 5xx | o SDK repete 2 vezes; se desistir, o caso é reexecutado uma vez; falhando de novo, `erro` `erro_llm` |
| 400 (inclui o limite de gasto do workspace), 401, 402, 403, outros 4xx, 429 sem `retry-after` | a rodada para na hora (código de saída 3); o caso não é gravado |
| 3 `erro_llm` seguidos | a rodada para (código 5). Valor inicial, a revisar depois da T09 |
| gasto chegou ao `--orcamento-usd` | a rodada para antes da próxima chamada (código 4) |

Valores iniciais a medir: timeout de 120 s por chamada e parada após 3 erros seguidos. A etapa 2 também confirma se a saída estruturada funciona com o pensamento adaptativo e se `output_tokens` inclui o thinking.

### Ensaio sem API paga (etapa 0)

`tests/ensaio_etapa0.py` roda os 4 casos da etapa 3 com o Maven de verdade e um modelo falso que responde o que o oráculo espera (código de teste; o agente em si nunca lê `casos/`):

```bash
PYTHONPATH=. python3 -m tests.ensaio_etapa0 --api ../rest-test-healing-sut --saida /tmp/ensaio
```

### Limites conhecidos da v1

- O Classifier só vê o módulo do teste em `src/main`; um problema real fora dele não é visto (D100). O piloto serve para ajustar isso (D99).
- A mensagem de falha mostra a primeira asserção que falhou, não todas.
- O Repair só troca o **corpo** do método; anotações e assinatura são as do original.
- O custo da chamada que falha sem resposta é registrado como zero; o gasto real se confere no Console.
- Nas rodadas 1 e 2, o modelo devolveu o método inteiro numa linha só em 2 de 6 reparos. Num método com bloco de texto (`"""`) isso não compila: o Java exige quebra de linha depois das aspas de abertura (A1-004, rodada 2). A regra 1 da D95 (idêntico ignorando espaços) ainda chama esse reparo de equivalente, mas as métricas só contam como correto o reparo que compila, passa **e** é equivalente. Por isso o prompt do Repair ganhou, no `51894a8`, o pedido de preservar quebras de linha e indentação (D99); na rodada 3, os 3 reparos mantiveram as quebras de linha, e o A1-004 compilou e passou.
- O comparador lê cada asserção como o `.andExpect(...)` inteiro, e não como uma linha: um reparo com o corpo do método numa linha só (o modelo fez isso no A1-001) é comparado do mesmo jeito que o original. Equivalente ao oráculo com troca de cenário ao mesmo tempo é inconsistente e vai para revisão manual. Na baseline e na v1, todo caso que vai para revisão manual sai com `equivalente_oraculo` nulo no `resultados-agente1.json`, e o veredito é preenchido à mão antes de calcular as métricas.

## Licença

MIT. Ver `LICENSE`.
