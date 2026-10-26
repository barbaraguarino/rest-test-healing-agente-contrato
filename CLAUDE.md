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

## Licença
- MIT (D65), com copyright em nome de Barbara Carvalho e João Vitor. O repositório fica privado até a entrega final.

## Estado do projeto
- O código da v1 (baseline determinística e pipeline fixo Classifier → Repair) está na tag `rodada-2`; os resultados do piloto só se regeneram com essa tag.
- A versão agêntica está sendo escrita do zero na `develop` (T23). Não inventar comandos, arquivos ou dependências que ainda não existem; atualizar esta seção quando forem criados.
