# Análise do Agente 1 (T27)

Saídas dos scripts da análise da execução final (`resultados/t25-final/`), de onde saem os números do artigo (D142). Nenhum arquivo da `t25-final` foi alterado. Sem LLM, sem API e sem Maven.

Os códigos D·· e T·· remetem ao registro interno do estudo, que não é publicado.

Versões: `rest-test-healing-avaliacao` na `master` em `0dd0fc7`; este repositório na `develop` em `ad331d4`.

| Arquivo | Como foi gerado (a partir da pasta do `rest-test-healing-avaliacao`) |
|---|---|
| `metricas.txt`, `metricas.json` | `python -m avaliacao ../rest-test-healing-agente-contrato/resultados/t25-final/resultados-agente1.json --json metricas.json` |
| `mcnemar.txt`, `mcnemar.json` | `python -m avaliacao.mcnemar ../rest-test-healing-agente-contrato/resultados/t25-final/resultados-agente1.json --json mcnemar.json` |
| `descritivo.txt`, `descritivo.json` | `python -I resultados/t25-final/analise-t27/scripts/descritivo_t27.py resultados/t25-final --json descritivo.json` (da pasta deste repositório): totais por tratamento e variação entre as repetições |
| `sensibilidade-d141/` | **Exploratório.** `python -I resultados/t25-final/analise-t27/scripts/sensibilidade_d141.py resultados/t25-final/resultados-agente1.json <cópia fora dos repositórios>`, que troca o `equivalente_oraculo` do A1-027 r1 e r3 dos agentes para `false` (D141) só na cópia; depois os dois comandos acima sobre a cópia. A cópia não é versionada |

O texto de cada `.txt` é a saída do terminal. A sensibilidade não substitui o resultado oficial.
