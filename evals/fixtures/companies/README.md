# Sites simulados de empresas fictícias

As empresas do dataset com a tag `synthetic_company` são **fictícias**. Elas usam domínios no TLD reservado `.example` (RFC 2606), que nunca resolve na internet real.

Cada arquivo `<domínio>.md` simula o conteúdo público do site da empresa (home e página "sobre"). Na avaliação, a ferramenta de pesquisa (T12) entrega esse conteúdo no lugar de uma busca real, e o agente o trata como **dado não confiável**, igual a qualquer site.

Regras:
- um arquivo por domínio `.example` do dataset (há teste para isso);
- o conteúdo traz só dados de empresa (porte, frota, cidade, setor), sem nomes de pessoas.
