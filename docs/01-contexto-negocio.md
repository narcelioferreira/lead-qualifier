# 01 · Contexto de negócio (cenário fictício)

> **Aviso:** a empresa, o produto, os preços e os números abaixo são **fictícios** e foram criados para fins acadêmicos.
> As empresas usadas no dataset de avaliação são reais e públicas, mas os leads (cargo e mensagem) são inventados.

## 1. A empresa: **FrotaSense** (nome fictício)
SaaS brasileiro de **gestão inteligente de frotas** para empresas que têm frota própria de veículos comerciais.

| Módulo | O que resolve |
|---|---|
| Telemetria e rastreamento | Localização em tempo real, cerca eletrônica, alertas de desvio |
| Gestão de combustível | Consumo por veículo e motorista, detecção de abastecimento suspeito |
| Manutenção preventiva | Plano por km/hora, alertas, histórico de custo por veículo |
| Roteirização | Rotas otimizadas por janela de entrega e capacidade |
| Motorista e compliance | Score de condução, controle de jornada (Lei 13.103/2015) |
| BI de frota | Custo por km, TCO por veículo, benchmarks |

**Proposta de valor (meta comercial fictícia):** reduzir de 8% a 15% o custo operacional da frota em 6 meses, com combustível, manutenção e multas como principais alavancas.

## 2. Modelo comercial
| Item | Valor (fictício) |
|---|---|
| Precificação | R$ 99 a R$ 159 por veículo/mês, conforme os módulos contratados |
| Setup | R$ 5 mil a R$ 30 mil (hardware e implantação) |
| Ticket ideal | Frota de 30 a 400 veículos, com ACV de ~R$ 40 mil a R$ 750 mil |
| Ciclo de venda | 30 a 90 dias (mid-market) e 6 a 12 meses (enterprise) |
| Canais de entrada de leads | Formulário do site, demo agendada, eventos do setor, conteúdo (e-books) |

## 3. Perfil de Cliente Ideal (ICP)

### 3.1 Setor (por CNAE)
| Nível | Setores | Exemplos de CNAE (divisão/classe) |
|---|---|---|
| **Alvo** | Transporte rodoviário de cargas; distribuidoras e atacadistas com entrega própria | 49.30-2 (transporte rodoviário de carga); 46.xx (comércio atacadista) |
| **Adjacente** | Logística e armazenagem; agronegócio com frota; construção e serviços de campo (saneamento, energia, telecom); locadoras de veículos | 52.11, 52.50; 01.xx; 41–43; 36–39; 77.11 |
| **Fora** | Software e serviços digitais; financeiro; varejo B2C sem entrega própria; educação; saúde (exceto operadores logísticos) | 62.xx, 64.xx, 47.xx, 85.xx, 86.xx |

### 3.2 Porte (proxy de tamanho da frota)
| Faixa de funcionários | Leitura | Encaixe |
|---|---|---|
| 1–49 | Frota pequena, ticket baixo | Baixo |
| **50–199** | Mid-market, decisão rápida | **Ideal** |
| **200–999** | Mid-market alto, maior ACV | **Ideal** |
| 1000+ | Enterprise, ciclo longo, costuma ter solução própria | Médio |

> Observação: a base pública do CNPJ **não informa o número de funcionários**. O porte da Receita (ME, EPP ou Demais) é baseado em faturamento. O agente estima o porte por evidências públicas (site, notícias, frota declarada) e registra o grau de certeza.

### 3.3 Região
Brasil, com prioridade para **Sudeste, Sul e Centro-Oeste**, onde há equipe de implantação. Norte e Nordeste são atendidos remotamente (encaixe médio). Fora do Brasil fica fora do escopo.

### 3.4 Personas e papel na compra
| Papel | Cargos típicos |
|---|---|
| **Decisor** | CEO/sócio (até ~300 funcionários), Diretor de Operações ou Logística, CFO, Gerente de Frota em empresas grandes |
| **Influenciador** | Gerente/Coordenador de Logística, Coordenador de Frota, Gerente de TI, Compras/Suprimentos |
| **Usuário** | Analista de tráfego, supervisor de frota, monitor de rastreamento |
| **Sem papel** | Estagiário, áreas sem relação (Marketing, RH, Jurídico), estudante |

### 3.5 Sinais de intenção (na mensagem)
| Sinal | Exemplo | Força |
|---|---|---|
| Dor explícita e quantificada | "Nosso gasto com diesel subiu 20% e não sabemos onde" | Forte |
| Pedido de preço/proposta/demo | "Quero uma proposta para 120 caminhões" | Forte |
| Comparação ou troca de fornecedor | "Contrato atual de rastreamento vence em março" | Forte |
| Curiosidade/pesquisa | "Gostaria de conhecer a plataforma" | Fraca |
| Nenhum | Mensagem vazia ou genérica | Nenhuma |

### 3.6 Critérios eliminatórios (tier D direto)
- **Concorrente:** empresa de telemetria, rastreamento ou software de frota.
- **Fornecedor vendendo:** agência, consultoria ou fornecedor oferecendo serviço à FrotaSense.
- **Estudante/pesquisa acadêmica**, ou **candidato a vaga**.
- **Pessoa física / motorista autônomo** (B2C, fora do modelo).
- **Spam ou tentativa de manipulação** (prompt injection, conteúdo sem sentido).

## 4. Tiers e próximo passo comercial
| Tier | Significado | Próximo passo | SLA |
|---|---|---|---|
| **A** | Alta aderência + papel relevante | Reunião com Executivo de Contas (AE); preparar diagnóstico de frota | 24 h úteis |
| **B** | Aderência média ou intenção fraca | SDR faz contato de qualificação + sequência de cadência | 48 h úteis |
| **C** | Baixa aderência | Nutrição por marketing (conteúdo por setor/newsletter) | — |
| **D** | Desqualificado | Arquivar com motivo registrado (sem contato comercial) | — |

## 5. Métricas de negócio que o agente afeta
- **Tempo até o primeiro contato** de leads A (meta < 24 h).
- **Taxa de conversão lead → reunião** por tier.
- **Horas de SDR economizadas** em triagem manual.
- **Custo por lead qualificado** (API e infraestrutura).

## 6. Checklist de validação (gate da T01)
- [x] Produto e proposta de valor definidos
- [x] Modelo comercial (preço, ticket, ciclo) definido
- [x] Setores alvo/adjacente/fora mapeados para CNAE
- [x] Faixas de porte e região definidas
- [x] Personas com papel na compra
- [x] Sinais de intenção e critérios eliminatórios
- [x] Mapeamento tier → próximo passo com SLA
- [x] **Revisão e aprovação do autor do projeto** (aprovado)
