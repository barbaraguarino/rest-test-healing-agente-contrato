# Rest Test Healing (Agente - Contrato)

Agente 1 do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). O agente repara testes de API quebrados por mudança no contrato OpenAPI da API cobaia (no artigo, API-alvo; repositório [`rest-test-healing-sut`](https://github.com/barbaraguarino/rest-test-healing-sut)) e não repara quando a quebra é uma regressão do código.

Os códigos D·· e T·· remetem ao registro interno do estudo, que não é publicado.

## Versões

A versão agêntica (Classifier e Repair em laço com ferramentas, D62) é a versão final do Agente 1: foi a usada na execução final do estudo (T25), cujos resultados estão em `resultados/t25-final/`. Este README é o guia de reprodução dessa versão.

A versão apresentada na Rodada 2 (baseline determinística e v1 com pipeline fixo Classifier → Repair) está preservada na tag **`rodada-2`** (commit `263862a`), com o código, os testes, os prompts e o README de execução da época.

## Reproduzir os resultados do artigo sem gastar

Os resultados da execução final já estão gravados em `resultados/t25-final/`. Para refazer as métricas, o teste de hipóteses e o relatório visual a partir deles, não é preciso chave, LLM nem Maven; basta o Python 3.

1. Clone os três repositórios na mesma pasta-mãe:

   ```bash
   git clone https://github.com/barbaraguarino/rest-test-healing-agente-contrato.git
   git clone https://github.com/barbaraguarino/rest-test-healing-avaliacao.git
   git clone https://github.com/barbaraguarino/rest-test-healing-sut.git
   ```

2. Métricas e teste de hipóteses, a partir da pasta `rest-test-healing-avaliacao` (veja o README dela):

   ```bash
   python -m avaliacao ../rest-test-healing-agente-contrato/resultados/t25-final/resultados-agente1.json
   python -m avaliacao.mcnemar ../rest-test-healing-agente-contrato/resultados/t25-final/resultados-agente1.json
   ```

   A saída deve ser igual a `resultados/t25-final/analise-t27/metricas.txt` e `mcnemar.txt`.

3. Totais de tempo, tokens e custo, a partir da pasta deste repositório:

   ```bash
   python -I resultados/t25-final/analise-t27/scripts/descritivo_t27.py resultados/t25-final
   ```

   A saída deve ser igual a `resultados/t25-final/analise-t27/descritivo.txt`.

4. O relatório visual dos reparos de cada caso já está em `relatorios/t25-final.html`; para gerá-lo de novo, veja "Relatório visual dos reparos" abaixo.

Para rodar o agente de novo (a rodada paga), siga a seção seguinte.

## Como reproduzir a versão agêntica

### O que é preciso

- Python 3.13 ou 3.14 e Java 21.
- Os repositórios lado a lado, na mesma pasta-mãe (veja o `git clone` acima): este, `rest-test-healing-sut` (a API cobaia, com a tag `linha-de-base-2`; o runner faz a cópia na tag sozinho) e, para validar o arquivo de resultados, `rest-test-healing-avaliacao`.
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
3. **Run**. A última linha diz `ENSAIO OK` ou `ENSAIO FALHOU`. Por padrão, roda os três tratamentos (baseline, agentes e agente único, D82), com o agente único em todos os casos; `--tratamentos baseline agentes` deixa o agente único de fora. Por padrão, usa o oráculo do piloto; `--oraculo casos/oraculo-agente1-final.json` roda os 24 casos finais (T25, D135; resultado em `resultados/t25-ensaio/`).

Ensaio da retomada (T53): em **Parameters**, acrescente `--interromper-em A1-007 1`. A rodada cai no meio dessa execução, depois do reparo salvo, como um Ctrl+C. Depois, troque `--interromper-em A1-007 1` por `--retomar`, com a mesma `--saida`, e clique em **Run** de novo. O LLM simulado grava cada chamada no `chamadas.jsonl` com custo zero, para a conta das chamadas sem registro aparecer.

### Baseline sem gastar (T51, D75)

A baseline é determinística e não usa LLM: lê a diferença do contrato (`contrato.py`) e aplica cada mudança no método de teste afetado (`agente_contrato/baseline.py`). Na alteração de tipo da resposta, mantém o matcher com o valor no tipo novo (`.value(is(0))` → `.value(is("0"))`, D114). Ela roda pelo próprio runner, sem chave e sem orçamento:

1. **Run → Edit Configurations → + → Python**, **Module name** `agente_contrato.rodar`, **Working directory** a raiz deste repositório.
2. **Parameters**: `--api ../rest-test-healing-sut --saida resultados/NOME-NOVO --tratamentos baseline`. Para o oráculo da T25, acrescente `--oraculo casos/oraculo-agente1-final.json`.
3. **Run**. Roda 1 repetição por caso (D92), não lê o `.env` e não pede `SIM`. Como na rodada paga, recusa código com mudança não gravada (código de saída 7).

Para comparar com a baseline da v1 (t42-baseline, tag `rodada-2`): **Module name** `tests.comparar_t42`, **Parameters** `--api ../rest-test-healing-sut --ensaio resultados/NOME-NOVO`. O script roda o código da v1 só em Python, sem Maven, compara caso a caso o resultado e o método reparado e grava `comparacao-t42.json` na pasta. A última linha diz `COMPARAÇÃO OK` se a única diferença é a da D114.

### Agente único (T49, D67, D97)

O agente único é a referência qualitativa da D02: **um só agente** que classifica e repara no mesmo laço, com as mesmas 4 ferramentas dos dois agentes (`ler_arquivo`, `ver_diferenca`, `rodar_teste` e `salvar_reparo`), o mesmo guarda dentro do `salvar_reparo` (D129) e o limite total de 10 chamadas (`agentes.rodar_agente_unico`, prompt `prompts/agente_unico.md`). Ele recebe a primeira mensagem do Classifier, sem a diferença do contrato, e termina com o JSON do rótulo (schema da D131), que vai só para o log. A decisão vem do arquivo: reparou se algum reparo foi aceito pelo guarda. O rótulo `problema_real` com reparo salvo fica marcado no log (`incoerente`).

Fica fora do teste estatístico e roda só nos 8 casos sorteados dos 24 finais (D97), 3 repetições, depois da baseline e dos agentes em cada caso (D82). O sorteio (`agente_contrato/sorteio.py`, semente 4949) está em `casos/sorteio-agente-unico.json`, gravado num commit anterior a qualquer execução: A1-015, A1-018, A1-019, A1-024, A1-026, A1-029, A1-031 e A1-035. Na T25: **Parameters** `--api ../rest-test-healing-sut --saida resultados/NOME-NOVO --oraculo casos/oraculo-agente1-final.json --tratamentos baseline agentes agente_unico --orcamento-usd VALOR`. O runner recusa o agente único (código de saída 7) se o sorteio tiver mudança não gravada, for de outro oráculo (por exemplo, o do piloto) ou citar caso fora do oráculo; o arquivo, o commit, a semente e os IDs vão para o log (`sorteio`), e a retomada recusa outro sorteio.

Tradução para o formato comum (D74, D87: `tratamento` `agente_unico`, `versao_agente` `agentica`), pelas regras da D129, D130 e D132: reparo aceito é `reparar` (mesmo com o limite depois; com resposta final inválida, erro `saida_invalida`); `problema_real` sem reparo é `nao_reparar` sem erro; sem reparo aceito, uma recusa do guarda dá `guarda`, o limite de 10 dá `limite_chamadas`, e o rótulo `legitima` ou uma resposta final inválida dão `saida_invalida`; o tempo do caso esgotado é `timeout` e vence o guarda.

### Configurar a chave (só para a rodada paga)

A rodada paga chama a API da Anthropic e precisa de uma chave **sua** (crie em [console.anthropic.com](https://console.anthropic.com)); o gasto vai para a sua conta. Como referência, a execução final (T25: 24 casos, baseline, agentes com 3 repetições e agente único nos 8 casos sorteados) fez 541 chamadas e custou US$ 0,60 (`resultados/t25-final/analise-t27/descritivo.txt`).

1. Copie `.env.example` para `.env`, na raiz do repositório.
2. Preencha `ANTHROPIC_API_KEY=` com a sua chave. O `.env` é ignorado pelo Git; a chave nunca vai para código, log, commit nem PR.

O código lê a chave só desse arquivo (`cliente_claude.ler_chave`), não da variável de ambiente.

### Rodada paga

`agente_contrato/rodar.py` é o runner. Para cada caso, em ordem de `id_caso` (D82): copia a API cobaia na tag, aplica o patch, roda o Maven inicial, roda o Classifier e o Repair (`rodar_agente`), confere o guarda no arquivo final (D129), roda o Maven final com o menor entre 120 s e o que resta do caso (D111, D123) e grava o resultado e o log. Em cada caso, a baseline roda antes dos agentes (D82), 1 vez (D92), com os mesmos cópia, patch, Maven inicial, guarda e Maven final, e sem LLM; `--tratamentos agentes` roda só os agentes.

1. **Run → Edit Configurations → + → Python**, **Module name** `agente_contrato.rodar`, **Working directory** a raiz deste repositório.
2. **Parameters**: `--api ../rest-test-healing-sut --saida resultados/NOME-NOVO --orcamento-usd 0.10`. Opções: `--repeticoes N` (padrão 3 nos agentes, D92; a baseline roda 1 vez), `--tratamentos baseline agentes agente_unico` (padrão: `baseline agentes`, D82; o agente único exige o sorteio, veja acima), `--casos A1-001 A1-004` (padrão: todos), `--oraculo casos/oraculo-agente1-final.json` (padrão: `casos/oraculo-agente1.json`, o do piloto; o final é o da T25) e `--retomar` (veja abaixo).
3. **Run**. O runner mostra a trava e pede que você digite `SIM` antes de chamar a API paga.

Travas antes de gastar:
- `--orcamento-usd` é obrigatório com os agentes ou o agente único, e vale para os dois juntos. O gasto é relido do `chamadas.jsonl` da pasta antes de cada chamada, e a rodada para ao chegar ao valor (D105); pode passar dele por no máximo uma chamada (cerca de US$ 0,009).
- O runner não roda com mudança não gravada em `prompts/` ou `agente_contrato/` (código de saída 7): o log precisa dizer com que prompt e código rodou (D105).
- O oráculo tem de estar dentro do repositório e sem mudança não gravada (código de saída 7). O arquivo e o commit dele vão para o log (`oraculo`).
- Sem `--retomar`, a pasta de saída deve ser nova: uma pasta com `resultados-agente1.json`, `log-agentica.json` ou `chamadas.jsonl` é recusada (código de saída 2).

Todas essas conferências acontecem antes de o runner ler a chave: uma pasta recusada não gasta nada.

### Retomar uma rodada interrompida (`--retomar`, T53)

Se a rodada parar no meio (queda de luz, Ctrl+C, orçamento esgotado, erro fatal ou 3 `erro_llm` seguidos), rode de novo com os **mesmos Parameters** e mais `--retomar`, com a mesma `--saida`. O runner:
- pula cada execução (caso, tratamento, repetição) que já está nos resultados **e** no log; a que está só num deles roda de novo;
- refaz do início a execução que parou no meio. As chamadas pagas dela ficam em `sessoes[].chamadas_sem_registro` do log, e o `custo_usd` da execução refeita soma só as chamadas da sessão que a terminou. Assim, cada chamada paga é contada uma vez: no registro de uma execução ou nas chamadas sem registro;
- conta o `--orcamento-usd` para a rodada inteira: o gasto começa do que já está no `chamadas.jsonl`, e a confirmação mostra quanto já foi gasto;
- recusa a pasta (código de saída 2) se a tag, o oráculo (arquivo ou commit), os prompts, o código ou os limites de tempo forem outros. Uma pasta de antes da T53, sem o oráculo no log, também é recusada;
- faz de novo o aquecimento do Maven (D111f), porque a retomada pode ser em outra hora ou outra máquina.

Cada vez que o comando roda vira uma entrada de `sessoes` no log. O contador de 3 `erro_llm` seguidos começa do zero em cada sessão.

Códigos de saída: 0 terminou; 3 erro que repetir não resolve (400, 401, 403, outros 4xx, inclusive o limite de gasto do workspace; D104, D108); 4 orçamento esgotado; 5 três `erro_llm` seguidos (D104); 6 prompt acima de 100 mil tokens (D106); 7 código ou prompts com mudança não gravada.

### O que a rodada grava (D89, D106)

| Arquivo | Conteúdo |
|---|---|
| `resultados-agente1.json` | Um registro por execução no formato comum (D74); é o arquivo que o validador da T20a lê |
| `chamadas.jsonl` | Uma linha por chamada ao Claude, gravada na hora, com o `tratamento` (T49), tokens, custo e `request_id`; linhas sem o `tratamento`, de antes da T49, são dos agentes |
| `log-agentica.json` | Tag, oráculo (arquivo e commit), limites, commits dos prompts e do código, `sessoes` (início, tratamentos, execuções já gravadas, chamadas sem registro e aquecimento do Maven de cada vez que o comando rodou), exclusões com a causa (D111e) e o porquê de cada execução, com o `tratamento`; na baseline, as mudanças aplicadas, as ignoradas com o motivo e as recusas do guarda |
| `execucoes/A1-NNN-rN/` | Agentes: `antes.java`, `depois.java`, `reparo.diff`, `caminho.json` (as ferramentas pedidas em cada volta) e `log.json` |
| `execucoes/A1-NNN-baseline-r1/` | Baseline: os mesmos arquivos, com `caminho.json` vazio (não há agente) |
| `execucoes/A1-NNN-agente_unico-rN/` | Agente único: os mesmos arquivos dos agentes, com um laço só no `caminho.json` |

A rodada grava `equivalente_oraculo` e `cenario_alterado` nulos. Quem os preenche, depois, é o comparador (T50), sem Maven e sem LLM.

### Comparar com a correção esperada (T50)

`agente_contrato/comparar_resultados.py` aplica o comparador (`agente_contrato/comparador.py`; D95, D109) às execuções com `decisao=reparar` de uma pasta já gravada:

- preenche `equivalente_oraculo` e `cenario_alterado` no próprio `resultados-agente1.json` (D138), sem mudar nenhum outro campo; o original fica no Git;
- grava ao lado o `comparacao.json`: para cada execução reparada, a regra da D95 que deu a equivalência (1, 2 ou 3), os motivos e, se for o caso, por que vai para a revisão manual (D80, D109);
- na revisão manual, `equivalente_oraculo` fica nulo (D110): a Barbara grava `true` ou `false` no `resultados-agente1.json` e o veredito e o motivo em `veredito_manual` e `motivo_do_veredito` do `comparacao.json`. Rodar de novo não apaga esse veredito;
- numa regressão reparada, `equivalente_oraculo` fica nulo e `cenario_alterado` é preenchido (D119).

A correção esperada e a diferença de contrato saem de uma cópia descartável da API cobaia na tag do log, com o patch do caso e a correção esperada congelada (D96), só com o Git. O oráculo é o gravado no log da rodada; antes da T53, o log não o tinha, e é preciso passar `--oraculo`.

No PyCharm: **Run → Edit Configurations → + → Python**, **Module name** `agente_contrato.comparar_resultados`, **Parameters** `--api ../rest-test-healing-sut --pasta resultados/t25-final`, **Working directory** a raiz do repositório. Depois disso, o validador só recusa os casos que esperam a revisão manual.

Para validar, na pasta `rest-test-healing-avaliacao`: **Run → Edit Configurations → + → Python**, **Module name** `avaliacao`, **Parameters** o caminho do `resultados-agente1.json`.

### Relatório visual dos reparos (T52)

`agente_contrato/relatorio_visual.py` gera uma página HTML por rodada, só com o que já está gravado: não roda Maven, não chama o LLM e não altera nada em `resultados/`. A página é um arquivo só, sem internet (CSS embutido, sem JS), e abre no celular. Para cada caso mostra o teste antes, a correção esperada do oráculo (lido só aqui, depois da execução) e, por tratamento (baseline, agentes r1 a r3, agente único), o reparo com as linhas mudadas, o caminho do agente, as recusas do guarda e: decisão, compilou, passou, erro, regra da D95, `cenario_alterado` e `equivalente_oraculo`. Nulo num legítimo reparado aparece como "revisão manual pendente". Não mostra métricas agregadas nem conclusões.

No PyCharm: **Run → Edit Configurations → + → Python**, **Module name** `agente_contrato.relatorio_visual`, **Parameters** `--pasta resultados/t25-final`, **Working directory** a raiz do repositório. A página sai em `relatorios/t25-final.html` (nunca dentro de `resultados/`); abra-a pelo PyCharm (botão direito no arquivo → **Open in → Browser**) ou pelo gerenciador de arquivos. Para o piloto, `--pasta resultados/t47-rodada-teste`, que não tem `comparacao.json`: a regra da D95 aparece como "sem comparação nesta rodada".

## Regenerar os resultados do piloto

Os resultados do piloto só se regeneram com o código da tag `rodada-2`: o código novo segue regras decididas depois do piloto (D114 a D116) e daria outro resultado em pelo menos um caso.

1. No PyCharm, abra a janela **Git**, aba **Log**.
2. Clique com o botão direito na tag `rodada-2` e escolha **Checkout**.
3. Siga o README que aparece nesse ponto.
4. Para voltar ao desenvolvimento, faça checkout da branch `develop`.

## Casos e oráculo

`casos/` guarda 36 casos: os 12 do piloto (A1-001 a A1-012, congelados na tag `oraculo-piloto`) e os 24 finais da execução do estudo (A1-013 a A1-036, T48, tag `oraculo-final`):

| Arquivo | Conteúdo |
|---|---|
| `casos/A1-NNN.patch` | A mudança do caso: código em `src/` e o `docs/openapi.json` novo, aplicados sobre a tag `linha-de-base-2` da API cobaia |
| `casos/A1-NNN.esperado.patch` | A correção esperada do teste afetado, só nos casos de mudança legítima |
| `casos/oraculo-agente1.json` | Oráculo do piloto: rótulo, categoria, lado, teste afetado e correção esperada de cada caso |
| `casos/oraculo-agente1-final.json` | Oráculo dos 24 casos finais, no mesmo formato |
| `casos/sorteio-agente-unico.json` | Os 8 casos finais sorteados para o agente único (semente 4949) |

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
| `resultados/t23j-d131/` | Uma chamada real do Classifier no A1-001, que confirmou que o modelo aceita o `output_config.format` junto com as ferramentas (D131); US$ 0,0003179 |
| `resultados/t47-rodada-teste/` | Rodada de teste paga da versão agêntica nos 12 casos do piloto, 1 repetição (T47), para medir tokens e custo; 66 chamadas, US$ 0,061937; não são resultados do estudo |
| `resultados/t53-ensaio-retomada/` | Ensaio da retomada (T53) nos 12 casos do piloto, Maven de verdade e LLM simulado, 1 repetição: a rodada cai no meio do A1-007 r1 e é retomada; `terminal-sessao1.txt` e `terminal-sessao2.txt` têm a saída de cada vez; não são resultados do estudo |
| `resultados/t51-ensaio/` | Ensaio da baseline nova (T51) nos 12 casos do piloto, Maven de verdade, 1 repetição, sem LLM; `comparacao-t42.json` compara com a t42-baseline da v1 (só o A1-007 muda, pela D114); não são resultados do estudo |
| `resultados/t49-ensaio/` | Ensaio do agente único (T49) nos 12 casos do piloto, Maven de verdade e LLM simulado, 1 repetição, com os três tratamentos (baseline, agentes e agente único, este nos 12 casos); `terminal.txt` tem a saída; não são resultados do estudo |
| `resultados/t51-ensaio-d133/` | O ensaio da T51 refeito depois da D133 (o `tempo_s` da baseline conta o Maven final), mesmos 12 casos e 1 repetição: `comparacao-t42.txt` (só o A1-007 muda, pela D114) e `comparacao-t51-ensaio.txt` (contra o `t51-ensaio`, só o `tempo_s` muda); não são resultados do estudo |
| `resultados/t25-ensaio/` | Ensaio da execução final nos 24 casos finais, Maven de verdade e LLM simulado (T25); não são resultados do estudo |
| `resultados/t25-final/` | **Execução final do estudo** (T25): 24 casos, baseline (1 repetição), agentes (3 repetições) e agente único (8 casos sorteados, 3 repetições); `resultados-agente1.json`, `chamadas.jsonl`, `log-agentica.json`, `comparacao.json` e `execucoes/` |
| `resultados/t25-final/analise-t27/` | Análise da execução final (T27): métricas, teste de hipóteses, descritivo e a sensibilidade exploratória da D141, com os comandos que geraram cada arquivo (README próprio) |
| `resultados/t48-conferencia/` | Conferência automática dos 24 casos finais (T48), sem LLM e sem API: `tabela.md` (a a e por caso) e `resultado.json`; não são resultados do estudo |

Os detalhes das rodadas anteriores à versão agêntica estão no README da tag `rodada-2`.

A pasta `relatorios/` guarda as páginas do relatório visual: `t25-final.html` (execução final) e `t47-rodada-teste.html` (rodada de teste).

## Repositórios do estudo

| Repositório | Papel |
|---|---|
| [`rest-test-healing-sut`](https://github.com/barbaraguarino/rest-test-healing-sut) | A API cobaia (no artigo, API-alvo); a versão do experimento é a tag `linha-de-base-2` |
| [`rest-test-healing-avaliacao`](https://github.com/barbaraguarino/rest-test-healing-avaliacao) | Validação do arquivo de resultados, métricas e teste de hipóteses |
| `rest-test-healing-agente-contrato` (este) | Agente 1: mudanças de contrato |
| [`rest-test-healing-agente-fixtures`](https://github.com/joaovitorbranq/rest-test-healing-agente-fixtures) | Agente 2: fixtures desatualizadas por mudança de regra de negócio |

## Licença

MIT. Ver `LICENSE`.
