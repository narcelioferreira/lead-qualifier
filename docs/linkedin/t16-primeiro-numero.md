# Material para post: o primeiro número real (T16)

Rodada única no split **test** (30 leads de empresas reais, nunca usados para ajustar prompt), comparando duas configurações com **a mesma pesquisa**:

- **baseline:** um prompt só; o LLM lê tudo e decide o tier;
- **MVP:** o LLM só extrai fatos da ontologia e justifica; o **código** pontua (rubrica, eliminatórias e tetos).

| | baseline | MVP |
|---|---:|---:|
| Acurácia (IC 95%) | 53,3% (33–70%) | **60,0% (43–77%)** |
| Kappa ponderado (IC 95%) | 0,475 (0,17–0,73) | **0,560 (0,31–0,77)** |
| Ataques (injeção/spam) desqualificados | 1/4 | **3/4** |
| Injeções que receberam tier A | **2** | 0 |
| Custo médio por lead (preço de lista) | US$ 0,00015 | US$ 0,00036 |

- **O ganho mais claro é em segurança.** No baseline, dois leads com injeção de prompt pediram "tier A" e receberam A. No MVP, um detector determinístico desqualificou 3 dos 4 ataques **antes** de qualquer chamada ao LLM.
- **Em acurácia, o MVP é melhor, mas os intervalos se sobrepõem:** com 30 leads, a diferença ainda não é conclusiva. Prefiro publicar o IC a publicar só o número bonito.
- **Dev 95% → test 60%.** O prompt v2 foi escrito olhando os erros do dev, e o test mostrou quanto disso não generaliza. É exatamente para isso que o test fica congelado. Nenhum ajuste foi feito com base nele.
- **Onde o MVP erra:** superestima transportadoras grandes (5 leads B viraram A), pesquisa a empresa errada em homônimos e não pega spam sem sentido. São os próximos alvos, trabalhados no dev.
- **Custo:** a avaliação inteira (dev + test, as duas configurações) rodou no plano gratuito da Groq. A cota diária acabou no meio do test e a mesma rodada foi completada no dia seguinte com retomada.
