# 🌾 Radar de Expositores · Feiras Agro 2027

Robô que, **a cada 30 minutos, 24/7**, varre notícias, portais do agro, sites oficiais das feiras, YouTube e redes sociais (Instagram, TikTok, X, LinkedIn e Facebook via Apify). Ele usa a **IA Claude** para identificar empresas que **confirmam, avaliam, especulam ou desistem** de expor nas feiras de 2027, publica tudo numa **página de notícias separada por segmento** e envia **e-mail** a cada novidade.

```
GitHub Actions (a cada 30 min)
  └─ radar.py
       ├─ fontes.py      → Google News, Bing News, RSS de portais, sites das feiras, YouTube, Apify
       ├─ pré-filtro     → só passa conteúdo que cita alguma feira (config.yaml)
       ├─ analise.py     → Claude: relevante? empresas, feira, segmento, intenção, resumo
       ├─ pagina.py      → docs/index.html (GitHub Pages: abre no celular)
       └─ notificacao.py → e-mail com os novos sinais
```

## O que você vai precisar (≈ 30 min de configuração)

| Item | Para quê | Custo estimado |
|---|---|---|
| Conta GitHub (repositório **público**) | Rodar 24/7 e hospedar a página | Grátis |
| Chave da API da Anthropic | Análise e resumos | ~US$ 5–20/mês |
| Conta Apify | Instagram, TikTok, X, LinkedIn e Facebook | US$ 5 grátis/mês; uso real ~US$ 30–60/mês com a configuração padrão |
| Chave da YouTube Data API (opcional) | Vídeos do YouTube | Grátis |
| Gmail com "senha de app" | Enviar as notificações | Grátis |

> ⚠️ O repositório precisa ser **público** para ter minutos ilimitados no GitHub Actions e o GitHub Pages grátis. Os dados coletados são informações públicas da internet, mas a página ficará acessível a quem tiver o link. Não suba o arquivo `.env`.

## Passo a passo

### 1. Criar o repositório
1. Crie uma conta em https://github.com e clique em **New repository** → nome `radar-feiras-2027` → **Public** → Create.
2. Instale o **GitHub Desktop** (https://desktop.github.com), clone o repositório e copie **todo o conteúdo desta pasta** para dentro dele (inclusive a pasta oculta `.github`). Depois faça **Commit** e **Push**.

### 2. Gerar as chaves
- **Anthropic:** https://console.anthropic.com → API Keys → Create Key. Adicione créditos em Billing.
- **Apify:** https://console.apify.com → Settings → API & Integrations → copie o *Personal API token*.
- **YouTube (opcional):** https://console.cloud.google.com → crie um projeto → ative a "YouTube Data API v3" → Credenciais → Criar chave de API.
- **Gmail:** ative a verificação em 2 etapas e crie uma senha de app em https://myaccount.google.com/apppasswords.
  *(Contas corporativas Microsoft 365 costumam bloquear SMTP; por isso a recomendação é usar um Gmail só para enviar.)*

### 3. Cadastrar os segredos no GitHub
No repositório: **Settings → Secrets and variables → Actions → New repository secret**. Crie:

`ANTHROPIC_API_KEY`, `APIFY_TOKEN`, `YOUTUBE_API_KEY`, `SMTP_HOST` (smtp.gmail.com), `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `EMAIL_TO`

### 4. Publicar a página
**Settings → Pages → Source: Deploy from a branch → Branch: `main` / pasta `/docs` → Save.**
O endereço será `https://SEU-USUARIO.github.io/radar-feiras-2027/`. Coloque esse endereço em `url_pagina` no `config.yaml`.

### 5. Ligar o robô
**Actions → Radar Feiras 2027 → Run workflow** (primeira execução manual). Depois disso ele roda sozinho a cada 30 minutos.

### 6. Push no celular
No app do Gmail/Outlook do celular, ative as notificações para o e-mail de destino. Se quiser, crie um filtro para o assunto **"Radar Feiras"** com prioridade alta, para ele não cair no meio dos outros e-mails.

## Personalização (`config.yaml`)
- **feiras:** inclua ou remova feiras e apelidos (`aliases`).
- **feeds_rss / sites_oficiais:** inclua portais e páginas que você acompanha.
- **apify → a_cada_horas:** principal controle de custo das redes sociais.
- **apify → hashtags / searchQueries / startUrls:** termos e páginas monitorados em cada rede.
- **claude → modelo:** troque para `claude-sonnet-4-5` se quiser análises mais refinadas (custa mais).
- **notificacao → confianca_minima_email:** suba esse valor se estiver recebendo e-mails demais.

## Rodar no próprio PC (teste)
```powershell
pip install -r requirements.txt
copy .env.exemplo .env      # e preencha as chaves
python radar.py --sem-ia    # testa só a coleta, sem gastar API
python radar.py             # rodada completa
```
Depois abra `docs/index.html` no navegador. O arquivo é autocontido, então também dá para abrir ou colar no Claude.

## Limitações reais
- Nenhum robô cobre "toda a internet". Aqui a cobertura vem de buscadores de notícias, portais do agro, sites oficiais e das 5 principais redes. Grupos fechados de WhatsApp/Telegram, stories que somem em 24h e posts privados ficam de fora.
- O GitHub pode atrasar o agendamento de 30 min em alguns minutos nos horários de pico.
- Se o repositório ficar 60 dias sem atividade, o GitHub pausa o agendamento e avisa por e-mail; basta reativar em **Actions**.
- Os atores do Apify são mantidos por terceiros. Se algum mudar o formato, ajuste a `entrada` dele no `config.yaml` conforme a página do ator em https://apify.com/store.

