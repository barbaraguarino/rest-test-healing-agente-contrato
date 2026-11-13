# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (`rest-test-healing-sut`) e não repara quando a quebra é uma regressão do código.

## Estado

A versão agêntica (Classifier e Repair em laço com ferramentas, D62) está sendo escrita do zero na branch `develop` (tarefa T23). Este README cresce junto com o código e, no fim, é o guia completo de reprodução.

A versão apresentada na Rodada 2 (baseline determinística e v1 com pipeline fixo Classifier → Repair) está preservada na tag **`rodada-2`** (commit `263862a`), com o código, os testes, os prompts e o README de execução da época.

## Como reproduzir a versão agêntica

### O que é preciso

- Python 3.13 ou 3.14 e Java 21.
- Os repositórios lado a lado, na mesma pasta-mãe: este, `rest-test-healing-sut` (a API cobaia, com a tag `linha-de-base-2`) e, para validar o arquivo de resultados, `rest-test-healing-avaliacao`.
- Linux ou Mac: o limite de tempo do Maven encerra o grupo de processos (`os.killpg`).

### Instalar (PyCharm)

1. Abra a pasta deste repositório como projeto.
2. **Settings → Project → Python Interpreter → Add Interpreter → Add Local Interpreter → Virtualenv**, na pasta `.venv` do projeto.
3. Abra `requirements.txt` e clique em **Install requirements** na faixa amarela (instala o `anthropic==1.17.0`).

### Rodar os testes (gratuito)

Botão direito na pasta `tests` → **Run 'Python tests in tests'**, com a raiz do repositório como pasta de trabalho. Nenhum teste chama a API paga: o LLM, o SDK e o Maven são simulados. Os testes do `registrar` usam o validador do `rest-test-healing-avaliacao` e são pulados se ele não estiver ao lado.

### Ensaio sem gastar (Maven de verdade, LLM simulado; D105)

`tests/ensaio.py` roda os 12 casos do piloto com o Maven de verdade e um "aluno perfeito": um LLM simulado que pede as ferramentas num roteiro fixo e entrega o rótulo e a correção do oráculo. Serve para provar o encanamento (cópia, patch, Maven inicial, ferramentas, guarda, Maven final, registro e log) antes de qualquer gasto. Só o ensaio lê o oráculo; o runner e o agente nunca leem.

1. **Run → Edit Configurations → + → Python**.
2. Em **Module name**, `tests.ensaio`; em **Parameters**, `--api ../rest-test-healing-sut --saida resultados/NOME-NOVO`; em **Working directory**, a raiz deste repositório.
3. **Run**. A última linha diz `ENSAIO OK` ou `ENSAIO FALHOU`. Leva cerca de 9 minutos (1 repetição).

### Configurar a chave (só para a rodada paga)

1. Copie `.env.example` para `.env`, na raiz do repositório.
2. Preencha `ANTHROPIC_API_KEY=` com a chave do workspace. O `.env` é ignorado pelo Git; a chave nunca vai para código, log, commit nem PR.

O código lê a chave só desse arquivo (`cliente_claude.ler_chave`), não da variável de ambiente.

### Rodada paga

`agente_contrato/rodar.py` é o runner. Para cada caso, em ordem de `id_caso` (D82): copia a API cobaia na tag, aplica o patch, roda o Maven inicial, roda o Classifier e o Repair (`rodar_agente`), confere o guarda no arquivo final (D129), roda o Maven final com o menor entre 120 s e o que resta do caso (D111, D123) e grava o resultado e o log. A baseline já tem o lugar na ordem e aparece como pendente até a T51.

1. **Run → Edit Configurations → + → Python**, **Module name** `agente_contrato.rodar`, **Working directory** a raiz deste repositório.
2. **Parameters**: `--api ../rest-test-healing-sut --saida resultados/NOME-NOVO --orcamento-usd 0.10`. Opções: `--repeticoes N` (padrão 3, D92) e `--casos A1-001 A1-004` (padrão: todos).
3. **Run**. O runner mostra a trava e pede que você digite `SIM` antes de chamar a API paga.

Travas antes de gastar:
- `--orcamento-usd` é obrigatório. O gasto é relido do `chamadas.jsonl` da pasta antes de cada chamada, e a rodada para ao chegar ao valor (D105); pode passar dele por no máximo uma chamada (cerca de US$ 0,009).
- O runner não roda com mudança não gravada em `prompts/` ou `agente_contrato/` (código de saída 7): o log precisa dizer com que prompt e código rodou (D105).
- A pasta de saída deve ser nova: ainda não há retomada de uma rodada interrompida.

Códigos de saída: 0 terminou; 3 erro que repetir não resolve (400, 401, 403, outros 4xx, inclusive o limite de gasto do workspace; D104, D108); 4 orçamento esgotado; 5 três `erro_llm` seguidos (D104); 6 prompt acima de 100 mil tokens (D106); 7 código ou prompts com mudança não gravada.

### O que a rodada grava (D89, D106)

| Arquivo | Conteúdo |
|---|---|
| `resultados-agente1.json` | Um registro por execução no formato comum (D74); é o arquivo que o validador da T20a lê |
| `chamadas.jsonl` | Uma linha por chamada ao Claude, gravada na hora, com tokens, custo e `request_id` |
| `log-agentica.json` | Limites, commits dos prompts e do código, aquecimento do Maven, exclusões com a causa (D111e) e o porquê de cada execução |
| `execucoes/A1-NNN-rN/` | `antes.java`, `depois.java`, `reparo.diff`, `caminho.json` (as ferramentas pedidas em cada volta) e `log.json` |

Até a T50 (comparador), `equivalente_oraculo` sai nulo, e o validador recusa o arquivo nos casos legítimos reparados (D110): é o esperado.

Para validar, na pasta `rest-test-healing-avaliacao`: **Run → Edit Configurations → + → Python**, **Module name** `avaliacao`, **Parameters** o caminho do `resultados-agente1.json`.

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
| `resultados/t23j-ensaio/` | Ensaio da versão agêntica nos 12 casos do piloto, Maven de verdade e LLM simulado, 1 repetição (T23j); não são resultados do estudo |

Os detalhes de cada rodada estão no README da tag `rodada-2` e na Operação do Estudo (repositório `rest-test-healing-estudo`).

## Licença

MIT. Ver `LICENSE`.
