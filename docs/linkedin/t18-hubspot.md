# Material para post: o agente escrevendo no CRM (T18)

- O agente agora grava o resultado no HubSpot: tier, score, confiança, próximo passo e o `run_id` da auditoria, na empresa e no contato, com uma Note de justificativa.
- **Rodar o mesmo lead duas vezes não pode duplicar registros.** O jeito óbvio (buscar e, se não achar, criar) falha: a busca do HubSpot leva alguns segundos para indexar o que acabou de ser criado. A solução foi um upsert atômico por uma propriedade de valor único (`ai_company_domain`), e por e-mail no caso do contato.
- **O CRM é uma superfície de ataque.** O texto da Note vem do LLM, que leu sites e mensagens não confiáveis. Por isso ele é escapado para HTML, e o agente só escreve numa allowlist de campos: não consegue trocar o dono do lead nem o estágio do funil.
- Achado: o próprio HubSpot criava uma empresa paralela a partir do domínio do e-mail do contato. Nem toda duplicata vem do seu código.
- 📸 Print: registro da empresa de teste no HubSpot com as propriedades "Qualificação por IA" e a Note (feito pelo autor).
