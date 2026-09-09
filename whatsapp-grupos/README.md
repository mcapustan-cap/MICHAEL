# Criar grupos de WhatsApp a partir de uma lista de contatos

Este projeto cria grupos de WhatsApp automaticamente a partir de uma planilha
de contatos (`.xlsx`). Ele funciona em duas etapas:

1. **`preparar_contatos.py`** — lê a planilha e gera um `contatos.json` já
   organizado nos grupos que você quer.
2. **`criar-grupos.js`** — conecta no seu WhatsApp (via QR Code, igual ao
   WhatsApp Web) e cria os grupos, adicionando os contatos.

---

## ⚠️ Leia antes de usar

- **Não existe API oficial** do WhatsApp para criar grupos. Este projeto usa a
  biblioteca **não-oficial** `whatsapp-web.js`, que automatiza o WhatsApp Web.
- Isso **viola os termos de uso** do WhatsApp. Criar muitos grupos ou adicionar
  muita gente rapidamente **pode levar ao banimento do número**. O risco existe
  e não é zero.
- **Recomendações para reduzir o risco:**
  - Use um **número secundário**, não o seu principal.
  - Comece sempre com `--simular` para ver o que seria feito.
  - Faça poucos grupos por dia; deixe as pausas do script agirem (não diminua).
  - Contatos que restringem "quem pode me adicionar a grupos" **não entram
    direto** — o script gera um **link de convite** para eles.
- A sessão fica salva na pasta `.wwebjs_auth/`. **Não compartilhe essa pasta** —
  ela dá acesso à sua conta do WhatsApp.

---

## Pré-requisitos

- **Node.js 18+** (para o `criar-grupos.js`) — https://nodejs.org
- **Python 3.9+** com `pandas` e `openpyxl` (para o `preparar_contatos.py`)
- Rodar **na sua máquina** (não em servidor), porque a sessão fica ligada ao seu
  celular via QR Code.

Instale as dependências:

```bash
# Dentro da pasta whatsapp-grupos/
npm install
pip install pandas openpyxl
```

---

## Passo 1 — Preparar os contatos

A planilha de exemplo (`Lista_Clientes_Set_2026.xlsx`) tem duas abas:

- **`Por Comercial`** — 70 clientes com a coluna `Comercial` (vendedor).
- **`tel`** — lista grande de contatos (`Nome Completo`, `CPF`, `Telefone`).

### Opção A — Um grupo por comercial (recomendado para a aba "Por Comercial")

```bash
python3 preparar_contatos.py Lista_Clientes_Set_2026.xlsx \
  --aba "Por Comercial" \
  --col-nome "Nome" \
  --col-tel "tel" \
  --col-grupo "Comercial" \
  --prefixo "Clientes - " \
  --comerciais comerciais.json \
  --fixos fixos.json
```

Isso cria um grupo para cada vendedor: `Clientes - AUGUSTO`, `Clientes - EDUARDO`, etc.

O `--comerciais comerciais.json` é **opcional**: se você preencher os telefones
em `comerciais.json`, cada comercial é incluído automaticamente no próprio grupo.
Deixe em branco os que não quiser incluir.

O `--fixos fixos.json` também é **opcional**: os contatos listados em `fixos.json`
entram em **todos** os grupos (ex.: o Pós Venda, um supervisor). Formato:

```json
[
  { "nome": "Pos Venda", "telefone": "51 9228-8548" }
]
```

### Opção B — Um único grupo com todos (aba "tel")

```bash
python3 preparar_contatos.py Lista_Clientes_Set_2026.xlsx \
  --aba "tel" \
  --col-nome "Nome Completo" \
  --col-tel "Telefone" \
  --nome-grupo "Clientes Setembro 2026"
```

> ⚠️ A aba `tel` tem ~2.300 números válidos. **Não** tente adicionar todos de uma
> vez — grupo do WhatsApp tem limite e o volume de adições quase certamente
> resultaria em banimento. Se precisar usar essa lista, divida em vários grupos
> menores e crie poucos por dia.

O comando mostra um resumo (grupos, contatos válidos, telefones incertos e linhas
ignoradas sem telefone) e grava o `contatos.json`.

---

## Passo 2 — Criar os grupos

**Sempre teste primeiro em modo simulação** (não cria nada, só mostra o plano):

```bash
node criar-grupos.js contatos.json --simular
```

Quando estiver satisfeito, rode de verdade:

```bash
node criar-grupos.js contatos.json
```

Na primeira vez aparece um **QR Code no terminal**. No celular, vá em
**WhatsApp → Aparelhos conectados → Conectar um aparelho** e escaneie.

O script:
- confirma quais números têm WhatsApp (resolve a variação do 9º dígito);
- cria cada grupo e adiciona os membros **em lotes, com pausas**;
- gera **link de convite** para quem não pôde ser adicionado direto;
- grava tudo em **`relatorio-grupos.json`** (quem entrou, quem não tem WhatsApp,
  quem precisa de convite e o link de cada grupo).

---

## Ajustar o ritmo

No topo do `criar-grupos.js`, no objeto `CFG`, você controla o ritmo:

| Opção | O que faz |
|---|---|
| `membrosPorLote` | quantos números adicionar por vez (padrão 8) |
| `pausaEntreLotesMs` | pausa entre lotes de membros (padrão 8s) |
| `pausaEntreGruposMs` | pausa entre um grupo e o próximo (padrão 20s) |
| `pausaVerificacaoMs` | pausa entre cada checagem de número (padrão 1,2s) |

Aumente os valores se quiser ir mais devagar (mais seguro).

---

## Formato do `contatos.json`

Você pode montar/editar esse arquivo à mão se preferir:

```json
{
  "grupos": [
    {
      "nome": "Clientes - EDUARDO",
      "contatos": [
        { "nome": "Fulano de Tal", "telefone": "5551999999999", "incerto": false }
      ]
    }
  ]
}
```

- `telefone`: formato internacional, só dígitos — `55` + DDD + número.
- `incerto`: `true` quando o número tem 10 dígitos (pode faltar o 9º dígito); o
  script tenta as duas variações no WhatsApp.
