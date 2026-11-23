# Sócio IA — 1.0 Beta

Time de agentes que trabalha dentro da empresa. Esta versão Beta entrega o **plano Essencial** com o Auditor incluído:

| Peça | O que faz no Beta |
|---|---|
| **Segundo Cérebro** | Registro de tudo o que acontece. O próprio banco recusa alteração e exclusão (gatilho SQL). |
| **Auditor** | Níveis 0–4 em código. Playbook só reduz autonomia; teto e regras invioláveis ficam em `socio_ia/auditor.py`. |
| **Financeiro** | Concilia Pix, boleto e cartão às 09h e 18h. Regras determinísticas, sem IA decidindo dinheiro. |
| **Dono** | Lê pendências às 07h e entrega o relatório às 19h. A IA (opcional) só escreve a abertura; números vêm do código. |
| **Empresa fictícia** | Padaria com 12 meses de dados e 15 erros plantados. O teste só passa se o sistema achar todos e nenhum a mais. |

**Fora do Beta (de propósito):** WhatsApp, Vendas, Marketing, Tráfego, RH, telas em React, Redis, LangGraph e busca vetorial.

## Rodar agora (sem Docker)

```bash
pip install -e ".[dev]"
pytest                 # 25 testes, incluindo o ponta a ponta da empresa fictícia
socio-ia demo          # gera a padaria, concilia 12 meses e imprime o relatório
```

## Rodar como servidor

```bash
cp .env.example .env   # troque a senha
docker compose up -d   # Postgres + API em http://127.0.0.1:8000/docs
# com modelo local para o texto do relatório:
docker compose --profile llm up -d && docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

## Fluxo de uso

1. `POST /importar/titulos` (CSV) e `POST /importar/extrato` (CSV ou OFX)
2. `POST /financeiro/conciliar` — ou espere o horário do Playbook
3. `GET /aprovacoes` → `POST /aprovacoes/{id}/aprovar` com `{"aprovador": "gestor"}`
4. `GET /relatorio`

Formatos de CSV: veja `socio_ia/importadores.py` (`COLS_TITULOS`, `COLS_EXTRATO`) ou gere um exemplo com `socio-ia gerar-ficticia dados/`.

## Regras de conciliação (ordem)

1. **Referência** — txid do Pix, nosso número do boleto, NSU do cartão
2. **CPF/CNPJ + valor + janela de datas**
3. **Valor + janela + nome parecido** → confiança baixa, sempre vai para aprovação

Cartão: compara o líquido recebido com a taxa contratada no Playbook e aponta quando a adquirente cobrou a mais.

## Limitações conhecidas do Beta

- **Autenticação fraca:** um token por instalação e o aprovador é informado pelo nome. Antes do primeiro cliente real é obrigatório login por usuário.
- **Entrada de dados manual:** o extrato é importado por arquivo. Integração com API de banco/adquirente vem com o piloto.
- **Primeira importação gera fila grande:** pagamentos sem referência nem documento caem todos em aprovação (60 na padaria). Falta aprovação em lote.
- **Banco SQLite nos testes, Postgres em produção:** o gatilho de imutabilidade existe nos dois, mas só o do SQLite está coberto por teste automático.
