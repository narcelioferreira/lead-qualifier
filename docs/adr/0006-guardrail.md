# ADR 0006: guardrail no mini, com SLM local de reserva

- **Status:** aceito (2026-10-30, T28)
- **Substitui:** o plano da arquitetura ("SLM local no guardrail, fallback no mini")
- **Evidência:** `evals/reports/guardrail-bench.md` e `evals/runs/guardrail-*.jsonl`

## Contexto

O guardrail é a primeira barreira do grafo: antes da pesquisa e da extração, ele decide se o
formulário do lead é injeção, spam ou fora de escopo. O plano era rodar um SLM de 1B a 4B no
Ollama, por três razões: custo de API zero, latência baixa e a mensagem do lead fora de
terceiros (LGPD). O mini (Groq) seria só o fallback.

Já havia uma camada determinística (`app/security/injection.py`, T16), mas ela só pega padrões
conhecidos. O guardrail serve para as variações que as regras não pegam.

Meta da T28: **recall de pelo menos 90% nas injeções, com no máximo 1 lead legítimo bloqueado.**

## Como foi medido

- **Conjunto:** 48 casos sintéticos (`evals/guardrail_set.jsonl`, revisados pelo autor) mais os
  20 leads do dev. São 24 injeções, 9 spams, 32 legítimos e 3 fora de escopo. Os 30 ataques
  sintéticos foram escritos para escapar das regras, e **nenhum** casa com elas. Os legítimos
  incluem as armadilhas: "ignorar a planilha antiga", "Nosso sistema:", "score de direção",
  inglês, espanhol, link do próprio site e urgência. O split test não entra.
- **Modelos:** `qwen3:4b`, `qwen3:1.7b` e `gemma3:1b` no Ollama, em CPU (8 núcleos, 7 GB de RAM,
  sem GPU), mais o `groq-mini` como referência. Todos usam o mesmo prompt (`v6/guardrail.md`) e
  respondem sozinhos, sem fallback, com 1 nova tentativa para saída fora do schema.
- **Ajuste do prompt:** depois de olhar 3 casos do conjunto, o prompt passou a ter o system prompt
  fixo (o nonce foi para a mensagem do usuário, o que liga o cache de prefixo e reduz a latência
  em cerca de 3×), uma definição mais direta de injeção ("fala com quem avalia") e a justificativa
  antes dos booleanos. Depois disso, o prompt ficou congelado até o fim do benchmark.

## Resultado

| Modelo | Injeções | Spam | Legítimos bloqueados | Latência p50 / p95 |
|---|---:|---:|---:|---:|
| `qwen3:4b` (39 de 68 casos) | 14/22 (64%) | 8/8 | 0/9 | 17,8 s / 26,1 s |
| `qwen3:1.7b` | 8/24 (33%) | 7/9 | 4/32 | 7,0 s / 10,1 s |
| `gemma3:1b` | 24/24 | 9/9 | **30/32** | 7,3 s / 8,1 s |
| `groq-mini` | **22/24 (92%)** | 9/9 | **0/32** | 4,7 s / 7,6 s |
| Só as regras | 2/33 ataques | | 0/32 | — |

- **Nenhum SLM atinge a meta.** O `gemma3:1b` marca quase tudo como injeção, inclusive os
  legítimos. O `qwen3:1.7b` deixa passar 2 de cada 3 injeções, entre elas as em inglês e
  espanhol, as escondidas em JSON ou HTML e as que vêm no cargo ou no nome da empresa.
- O `qwen3:4b` foi o mais preciso, com 0 legítimos bloqueados, mas já tinha errado 8 injeções
  quando a rodada foi interrompida por **falta de memória** da máquina. Mesmo acertando todas as
  restantes, ficaria em 67%. Por isso a rodada não foi repetida.
- O mini atinge a meta e deixa passar só o JSON embutido (G011) e o diálogo forjado com o
  assistente (G014).

## Decisão

1. O guardrail roda no **mini**, depois das regras determinísticas.
2. O **`qwen3:4b`** (já no catálogo, `ollama-slm`) fica de **reserva** quando o mini falha
   (indisponível ou saída inválida duas vezes). Ele foi escolhido entre os três pela precisão:
   como reserva, bloquear lead legítimo custa mais caro que deixar passar uma injeção, que ainda
   enfrenta o `normalize` e o score em código.
3. Injeção e spam viram a flag da ontologia, e o código aplica a K1: o lead vai direto ao
   `compute_score`, sem pesquisa nem extração. **Fora de escopo só é registrado**, porque
   estudante, candidato, fornecedor e pessoa física já têm regras próprias (K3, K4 e K5),
   decididas com evidência.
4. Se o mini e o SLM falharem, o lead segue (**fail open**), com o erro registrado. As regras e a
   flag de injeção do `normalize` ainda valem depois.

## Consequências

- **Custo:** cerca de 860 tokens do mini por lead (mais ~10% sobre os ~8K da configuração `rag`).
  Em compensação, um lead barrado deixa de gastar a pesquisa e a extração.
- **Latência:** no grafo real, o guardrail no mini respondeu em ~0,5 s. No benchmark, as chamadas
  mais rápidas levaram 0,4 s e a maioria ficou entre 4 e 8 s. Provavelmente é a espera do limite
  de 8K tokens por minuto do plano gratuito, já que as 68 chamadas rodaram em sequência (não
  medido à parte).
- **LGPD:** a mensagem do lead continua indo à Groq (o e-mail, não). Manter o texto só no SLM
  local não foi possível com a qualidade exigida neste hardware. O risco fica registrado em
  `docs/06-seguranca-agentes.md`.
- **A reserva vale pouco quando a Groq cai de vez:** o `normalize` também usa o mini, e a
  execução falharia mais adiante. O SLM cobre a falha pontual do guardrail (timeout, saída
  inválida) e mantém o grafo testável com o Ollama.
- **Ablação de routing (T30):** a configuração com guardrail é medida lá, com custo e acurácia.

## Alternativas descartadas

- **Ajustar o prompt do SLM com exemplos (few-shot):** prompt maior é mais lento em CPU, e com 24
  injeções o risco de ajustar ao próprio conjunto é alto.
- **Modelos treinados para guarda** (`llama-guard3:1b`, `granite3-guardian:2b`): foram feitos para
  conteúdo nocivo e jailbreak genérico, e não para "manipular a nota de um lead". Ficam como
  possibilidade com GPU.
- **SLM maior (7B a 8B):** não cabe na RAM desta máquina ao lado do Postgres e dos containers.
