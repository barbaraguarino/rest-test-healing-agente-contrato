# Instruções para o Claude

Repositório do agente 1 de contrato de "Manutenção de Testes de APIs REST usando Agentes de IA" (disciplina IA Generativa para Engenharia de Software, 2026.2).

## Commits e pull requests
- Nunca incluir link de sessão ou de chat do claude.ai em mensagens de commit, descrições de PR, comentários ou documentos. Isso inclui o trailer `Claude-Session` e a linha com o link no fim da descrição do PR.
- Trabalhar sempre num branch próprio; nunca fazer commit na `master` nem aprovar ou mesclar PR.
- Só gravar depois que a Barbara disser "Pode gravar".

## Casos e oráculo
- `casos/` guarda os casos do estudo e o oráculo (`oraculo-agente1.json`). O agente nunca recebe nem lê nada de `casos/` além do patch que o código aplica na API cobaia; o rótulo do oráculo só é copiado para o resultado depois da execução.
- Depois das tags `oraculo-piloto` e `oraculo-final`, não alterar os arquivos congelados; uma mudança necessária é registrada como desvio na Operação do Estudo.
