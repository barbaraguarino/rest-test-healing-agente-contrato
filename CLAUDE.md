# Instruções para o Claude

Repositório do Agente 1 (contrato) do estudo "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2). Os documentos do estudo (Planejamento, Registro de Decisões, Cronograma e Tarefas) ficam no repositório `rest-test-healing-estudo`; as decisões são citadas pelo código (ex.: D62) e as tarefas também (ex.: T23).

## Links de sessão
- Nunca incluir link de sessão ou de chat do claude.ai em mensagens de commit, descrições de PR, comentários ou documentos. Isso inclui o trailer `Claude-Session` e a linha com o link no fim da descrição do PR.

## Quando gravar
- Commit, push e PR só depois que a Barbara disser "Pode gravar". A permissão vale só para o passo atual; o passo seguinte precisa de outra.
- Nunca aprovar nem mesclar PR.

## Git Flow
- `master`: só versões entregues, cada uma com tag (ex.: `rodada-2`).
- `develop`: integração; recebe as features por PR.
- `feature/<tarefa>-<descricao>`: sai da `develop` e volta para ela por PR. O nome começa pelo código da tarefa do Cronograma e Tarefas (ex.: `feature/T23b-rodar-teste`), e o PR cita a tarefa. Não se usam Issues: as tarefas ficam no Cronograma, que o João acompanha.
- `release/*`: prepara uma entrega da `develop` para a `master`.
- `hotfix/*`: correção urgente sobre a `master`.
- Nada é gravado direto na `master` nem na `develop`.

## Commits
- Pequenos e frequentes: uma mudança por commit (uma função, um teste, um ajuste), com mensagem clara em português.
- Nunca um arquivo grande inteiro num commit só: o código cresce como uma pessoa o escreveria, função por função, até formar a classe e o arquivo.

## Aprender primeiro
A Barbara está aprendendo agentes de IA e teste de software e precisa saber explicar cada linha deste repositório.
- Antes de escrever, explicar: teoria, com analogia, depois o porquê e só então o como. Confirmar que ela entendeu antes de seguir.
- Escrever em passos pequenos e pausar depois de cada um, com a explicação da lógica geral e linha a linha.
- Dizer sempre o que é decidido pelo LLM e o que é código determinístico comum.
- Termos novos de IA generativa, agentes ou teste de software são explicados na primeira vez que aparecem.

## Execução
- A Barbara roda o agente pelo PyCharm. As instruções de execução dizem o que clicar, não comandos de terminal.
- Testes automatizados usam um LLM simulado. Nenhum teste chama a API paga.

## Custo
- Nunca chamar a API paga do Claude sem avisar antes, com o custo estimado e a fonte do preço. O Agente 1 tem US$ 2 do teto do workspace (D60).

## Casos e oráculo
- `casos/` guarda os casos do estudo e o oráculo (`oraculo-agente1.json`). O agente nunca recebe nem lê nada de `casos/` além do patch que o código aplica na API cobaia e do nome do teste afetado (`teste_afetado`, D112); o rótulo do oráculo só é copiado para o resultado depois da execução.
- Depois das tags `oraculo-piloto` e `oraculo-final`, não alterar os arquivos congelados; uma mudança necessária é registrada como desvio na Operação do Estudo.
- `resultados/` guarda as evidências das rodadas já feitas e não é apagado.

## Protocolo
Estas regras foram fechadas antes dos resultados. Se uma mudança de código exigir mexer nelas, parar e avisar a Barbara: vira decisão nova ou desvio declarado no Registro de Decisões, e o que afeta o formato comum de resultados precisa do acordo do João.
- Casos, oráculo e tags: D91 a D96.
- Métricas e formato comum de resultados: D74, D110, D118, D119.
- Repetições e agregação: D81, D92.
- Parâmetros do LLM: D61.
- Baseline: D75, com a convenção da D114.

## Reprodutibilidade
- Sementes fixas onde houver sorteio.
- Sem caminhos absolutos no código.
- Dependências com versão fixada quando existirem.

## Licença
- MIT (D65), com copyright em nome de Barbara Carvalho e João Vitor. O repositório fica privado até a entrega final.

## Estado do projeto
- O código da v1 (baseline determinística e pipeline fixo Classifier → Repair) está na tag `rodada-2`; os resultados do piloto só se regeneram com essa tag.
- A versão agêntica está sendo escrita do zero na `develop` (T23). Não inventar comandos, arquivos ou dependências que ainda não existem; atualizar esta seção quando forem criados.
- A pasta `.claude/` guarda a configuração do Claude Code: `settings.json` (permissões allow/ask/deny) e o hook `hooks/bloquear-links-de-sessao.sh`, que barra commit, PR e issue com link de sessão ou de chat do claude.ai. O hook precisa do `jq`; sem ele, não funciona.
- T23b feita (branch `feature/T23b-rodar-teste`): `agente_contrato/execucao.py` roda o teste afetado na API cobaia, sem LLM. `preparar_copia` clona a API e fixa a tag; `aplicar_patch` confere e aplica o patch do caso; `rodar_teste` roda `mvnw -Dtest=Classe*#metodo` com o limite de 120 s (D111a) e lê as súmulas do Surefire (`ler_relatorios`), e só vale se exatamente um teste rodou; `rodar_teste_inicial` refaz um estouro uma vez e depois dá `erro_execucao` (D111e); `rodar_teste_final` trata o estouro como `timeout` (D111d, D118). `rodar_com_limite` e `encerrar_grupo` usam grupo de processos (`os.killpg`) e por isso valem só para Linux e Mac. Os testes estão em `tests/` e usam `tests/processo_falso.py` e `tests/maven_falso.py` no lugar do Maven; rodam pelo PyCharm (botão direito na pasta `tests`, Run), com a raiz do repositório como pasta do projeto.
- T23c feita (branch `feature/T23c-laco-agente`): `agente_contrato/laco.py` tem os tipos da conversa, que imitam `tool_use` e `tool_result` da API do Claude; `executar_pedido`, em que uma ferramenta desconhecida volta ao modelo como erro (`erro=True`) e o laço segue; e `rodar_laco`, que para quando o modelo termina (`terminou`), no limite de chamadas (`limite_de_chamadas`) ou quando o tempo do caso acaba (`limite_do_caso`). `agente_contrato/relogio.py` tem `RelogioCaso`: 180 s a partir do Maven inicial, pausado durante a espera do LLM (D111b, D118), e `limite_para_teste`, o menor entre 120 s e o que resta do caso. Os testes usam um LLM simulado (`ModeloSimulado`, em `tests/test_rodar_laco.py`) e `tests/relogio_falso.py` no lugar do `time.monotonic`. Falta ligar `limite_para_teste` ao Maven final, no runner (T23j).
- T23d feita (branch `feature/T23d-diferenca-contrato`): `agente_contrato/contrato.py` calcula a diferença entre o contrato OpenAPI antigo e o novo, sem LLM (D62, D100). `carregar` lê o `openapi.json`; `resolver` segue o `$ref` sem entrar em círculo; `achatar_schema` e `achatar` montam, para cada (método, rota, lado), a planilha `{caminho do campo: Propriedade}`, com `[]` nos itens de lista; `diferenca` devolve a lista de `Mudanca` nas 4 categorias da v1 (renomeação, remoção, alteração de tipo e campo obrigatório novo); `descrever_mudancas` escreve o texto que o modelo lê, igual ao da v1. Limites mantidos da v1: só entram o corpo da requisição e o das respostas 2xx, e uma operação removida não aparece. Testes em `tests/test_contrato.py`.
- T23e feita (branch `feature/T23e-ferramentas`): `agente_contrato/ferramentas.py` tem as ferramentas do agente. `ler_arquivo` lê só nas pastas da D73 e, numa pasta, lista os arquivos; `ver_diferenca` compara o contrato do HEAD da cópia (a tag) com o contrato depois do patch e devolve o texto da T23d (D122); `rodar_teste` roda sempre o teste afetado (D112) com `limite_para_teste` do relógio do caso e devolve se passou, se não compilou ou a mensagem de falha. Uma recusa e um estouro de tempo levantam `ErroDeFerramenta` e voltam ao modelo como erro; uma falha de infraestrutura (`ErroDeExecucao`) para o caso (D124). `execucao.py` ganhou `ler_falha`, que lê a primeira falha do Surefire sem stack trace, cortada em 1.500 caracteres (D100b). `agente_contrato/teste_java.py` tem `localizar_metodo`, igual ao da v1: acha o corpo de `void nome(...)`, que deve aparecer uma vez, contando as chaves e pulando textos, text blocks e comentários (`_depois_do_literal`); um `\"""` escapado dentro de text block não é tratado. `salvar_reparo` recebe do modelo o método inteiro (D101) e troca só o corpo do método afetado, mantendo anotações e assinatura do original (D116); um método que não se acha no texto do modelo volta a ele como erro, e o arquivo é lido e gravado em bytes para manter as quebras de linha. `DEFINICOES` tem o nome, a descrição em português (D70) e o `input_schema` de cada ferramenta, no formato `tools` da API do Claude, sem nada do desenho do experimento (D73); `montar` liga cada nome à função, com raiz, arquivo, classe, método e relógio do caso preenchidos pelo código, e um campo obrigatório que falta volta ao modelo como erro. Quem recebe qual ferramenta (Classifier ou Repair) é a T23f. Testes em `tests/test_ler_arquivo.py`, `test_ver_diferenca.py`, `test_ler_falha.py`, `test_ferramenta_rodar_teste.py`, `test_teste_java.py`, `test_salvar_reparo.py` e `test_definicoes.py`.
