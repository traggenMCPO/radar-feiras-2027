"""Coletores de conteúdo: notícias, feeds RSS, sites oficiais, YouTube e redes sociais (Apify)."""
import hashlib
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse, urlencode, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

log = logging.getLogger("radar")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5"})


# ----------------------------------------------------------------- utilidades
def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in txt if not unicodedata.combining(c)).lower()


def limpar_html(txt: str) -> str:
    if not txt:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(txt, "html.parser").get_text(" ")).strip()


def url_canonica(url: str) -> str:
    try:
        p = urlparse(url.strip())
        q = [(k, v) for k, v in parse_qs(p.query).items() if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        query = urlencode([(k, v[0]) for k, v in q])
        return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url


def gerar_id(url: str) -> str:
    return hashlib.sha1(url_canonica(url).encode("utf-8")).hexdigest()[:16]


def para_iso(valor) -> str | None:
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)):
            v = valor / 1000 if valor > 1e11 else valor
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        if isinstance(valor, time.struct_time):
            return datetime(*valor[:6], tzinfo=timezone.utc).isoformat()
        d = dtparser.parse(str(valor))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def novo_item(url, titulo, texto="", fonte="", tipo="noticia", rede="Web", imagem=None, publicado=None, autor=None):
    return {
        "id": gerar_id(url),
        "url": url,
        "titulo": (titulo or "").strip()[:300],
        "texto": (texto or "").strip()[:4000],
        "fonte": fonte,
        "tipo": tipo,          # noticia | video | social | site
        "rede": rede,          # Google News, Bing, RSS, YouTube, Instagram, ...
        "imagem": imagem,
        "publicado": para_iso(publicado),
        "autor": autor,
    }


def _get(url, **kw):
    kw.setdefault("timeout", 25)
    r = SESSION.get(url, **kw)
    r.raise_for_status()
    return r


def _paralelo(func, tarefas, workers=6):
    saida = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(func, tarefas):
            saida.extend(res or [])
    return saida


# ----------------------------------------------------------------- Google News
def _google_news(consulta: str):
    url = ("https://news.google.com/rss/search?q=" + quote_plus(consulta + " when:30d")
           + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")
    try:
        feed = feedparser.parse(_get(url).content)
    except Exception as e:
        log.warning("Google News falhou [%s]: %s", consulta, e)
        return []
    itens = []
    for e in feed.entries:
        fonte = (e.get("source") or {}).get("title", "Google News")
        titulo = re.sub(r"\s+-\s+[^-]+$", "", e.get("title", ""))
        itens.append(novo_item(e.link, titulo, limpar_html(e.get("summary", "")), fonte,
                               rede="Google News", publicado=e.get("published_parsed")))
    time.sleep(0.5)
    return itens


def coletar_google_news(cfg):
    consultas = [f'"{f["nome"]}" {cfg["termos_participacao"]}' for f in cfg["feiras"]]
    consultas += cfg.get("consultas_extras", [])
    return _paralelo(_google_news, consultas, workers=4)


# ----------------------------------------------------------------- Bing News
def _bing_news(consulta: str):
    url = "https://www.bing.com/news/search?" + urlencode(
        {"q": consulta, "format": "rss", "setlang": "pt-BR", "cc": "BR", "qft": 'sortbydate="1"'})
    try:
        feed = feedparser.parse(_get(url).content)
    except Exception as e:
        log.warning("Bing falhou [%s]: %s", consulta, e)
        return []
    itens = []
    for e in feed.entries:
        link = e.get("link", "")
        real = parse_qs(urlparse(link).query).get("url", [link])[0]
        img = e.get("news_image")
        if img and "bing.com/th" in img:
            img = img.split("&pid=")[0] + "&w=640&h=360&c=7"
        itens.append(novo_item(real, e.get("title", ""), limpar_html(e.get("summary", "")),
                               e.get("news_source", "Bing"), rede="Bing News", imagem=img,
                               publicado=e.get("published_parsed")))
    time.sleep(0.5)
    return itens


def coletar_bing(cfg):
    consultas = [f'"{f["nome"]}" 2027' for f in cfg["feiras"]]
    consultas += [f'"{f["nome"]}" expositores' for f in cfg["feiras"]]
    consultas += cfg.get("consultas_extras", [])
    return _paralelo(_bing_news, consultas, workers=4)


# ----------------------------------------------------------------- RSS de portais
def _imagem_entry(e):
    for chave in ("media_content", "media_thumbnail"):
        for m in e.get(chave) or []:
            if m.get("url"):
                return m["url"]
    for enc in e.get("enclosures") or []:
        if str(enc.get("type", "")).startswith("image"):
            return enc.get("href")
    m = re.search(r'<img[^>]+src="([^"]+)"', e.get("summary", "") + str(e.get("content", "")))
    return m.group(1) if m else None


def _rss(url):
    try:
        feed = feedparser.parse(_get(url).content)
    except Exception as e:
        log.warning("RSS falhou [%s]: %s", url, e)
        return []
    nome = feed.feed.get("title", urlparse(url).netloc)
    itens = []
    for e in feed.entries:
        texto = limpar_html(e.get("summary", ""))
        if e.get("content"):
            texto = limpar_html(e.content[0].get("value", "")) or texto
        itens.append(novo_item(e.get("link", ""), e.get("title", ""), texto, nome, rede="Portal (RSS)",
                               imagem=_imagem_entry(e), publicado=e.get("published_parsed") or e.get("updated_parsed")))
    return itens


def coletar_rss(cfg):
    return _paralelo(_rss, cfg.get("feeds_rss", []), workers=6)


# ----------------------------------------------------------------- sites oficiais
PALAVRAS_SITE = ("2027", "expositor", "estande", "stand", "edicao", "inscric", "lancament", "particip", "novidade")


def _site(url):
    try:
        html = _get(url).text
    except Exception as e:
        log.warning("Site falhou [%s]: %s", url, e)
        return []
    soup = BeautifulSoup(html, "html.parser")
    dominio = urlparse(url).netloc
    itens, vistos = [], set()
    for a in soup.find_all("a", href=True):
        texto = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        if len(texto) < 25 or not any(p in normalizar(texto) for p in PALAVRAS_SITE):
            continue
        link = urljoin(url, a["href"])
        if link in vistos or not link.startswith("http"):
            continue
        vistos.add(link)
        itens.append(novo_item(link, texto, texto, f"Site oficial ({dominio})", tipo="site", rede="Site oficial"))
        if len(itens) >= 20:
            break
    return itens


def coletar_sites(cfg):
    return _paralelo(_site, cfg.get("sites_oficiais", []), workers=5)


# ----------------------------------------------------------------- YouTube
def coletar_youtube(cfg, estado, chave):
    yt = cfg.get("youtube", {})
    if not (yt.get("ativo") and chave):
        return []
    feiras = cfg["feiras"]
    idx = estado.get("youtube_idx", 0)
    depois = (datetime.now(timezone.utc) - timedelta(days=cfg.get("janela_dias", 45))).strftime("%Y-%m-%dT%H:%M:%SZ")
    itens = []
    for _ in range(yt.get("buscas_por_execucao", 2)):
        feira = feiras[idx % len(feiras)]
        idx += 1
        try:
            r = _get("https://www.googleapis.com/youtube/v3/search", params={
                "part": "snippet", "type": "video", "q": f'{feira["nome"]} {cfg["ano_alvo"]} OR expositores',
                "regionCode": "BR", "relevanceLanguage": "pt", "order": "date", "maxResults": 25,
                "publishedAfter": depois, "key": chave})
            for v in r.json().get("items", []):
                s = v["snippet"]
                vid = v["id"]["videoId"]
                thumb = (s.get("thumbnails", {}).get("high") or s.get("thumbnails", {}).get("default") or {}).get("url")
                itens.append(novo_item(f"https://www.youtube.com/watch?v={vid}", s.get("title", ""),
                                       s.get("description", ""), s.get("channelTitle", "YouTube"), tipo="video",
                                       rede="YouTube", imagem=thumb, publicado=s.get("publishedAt"),
                                       autor=s.get("channelTitle")))
        except Exception as e:
            log.warning("YouTube falhou [%s]: %s", feira["nome"], e)
    estado["youtube_idx"] = idx % len(feiras)
    return itens


# ----------------------------------------------------------------- Apify (Instagram, TikTok, X, LinkedIn, Facebook)
def _pegar(d, *caminhos):
    for cam in caminhos:
        atual = d
        for parte in cam.split("."):
            if isinstance(atual, dict):
                atual = atual.get(parte)
            elif isinstance(atual, list) and parte.isdigit() and int(parte) < len(atual):
                atual = atual[int(parte)]
            else:
                atual = None
            if atual is None:
                break
        if atual not in (None, "", []):
            return atual
    return None


def _normalizar_apify(reg, rede):
    url = _pegar(reg, "url", "postUrl", "webVideoUrl", "link", "permalink", "post_url", "shareUrl", "linkedinUrl")
    if not url or not isinstance(url, str):
        return None
    texto = _pegar(reg, "caption", "text", "fullText", "content", "description", "postText", "commentary", "message")
    imagem = _pegar(reg, "displayUrl", "thumbnailUrl", "videoMeta.coverUrl", "covers.0", "imageUrl", "image",
                    "images.0", "media.0.url", "media.0.media_url_https", "extendedEntities.media.0.media_url_https",
                    "postImages.0.url", "thumbnail")
    if isinstance(imagem, dict):
        imagem = imagem.get("url")
    publicado = _pegar(reg, "timestamp", "createTimeISO", "createdAt", "postedAtISO", "postedAt.date", "postedAt",
                       "time", "date", "publishedAt", "createTime")
    autor = _pegar(reg, "ownerUsername", "ownerFullName", "authorMeta.name", "author.userName", "author.name",
                   "pageName", "user.name", "authorName", "author.fullName")
    texto = str(texto or "")
    titulo = (f"@{autor}: " if autor else "") + texto[:140]
    return novo_item(url, titulo, texto, rede, tipo="social", rede=rede,
                     imagem=imagem if isinstance(imagem, str) else None, publicado=publicado,
                     autor=str(autor) if autor else None)


def coletar_apify(cfg, estado, token):
    ap = cfg.get("apify", {})
    if not (ap.get("ativo") and token):
        return []
    agora = datetime.now(timezone.utc)
    ultimas = estado.setdefault("apify_ultima", {})
    itens = []
    for ator in ap.get("atores", []):
        nome = ator["nome"]
        ultima = ultimas.get(nome)
        if ultima and agora - datetime.fromisoformat(ultima) < timedelta(hours=ator.get("a_cada_horas", 2)) - timedelta(minutes=5):
            continue
        endpoint = f"https://api.apify.com/v2/acts/{ator['ator'].replace('/', '~')}/run-sync-get-dataset-items"
        try:
            r = SESSION.post(endpoint, params={"token": token, "timeout": 240}, json=ator.get("entrada", {}), timeout=300)
            r.raise_for_status()
            regs = r.json()
            n = 0
            for reg in regs if isinstance(regs, list) else []:
                it = _normalizar_apify(reg, nome)
                if it:
                    itens.append(it)
                    n += 1
            ultimas[nome] = agora.isoformat()
            log.info("Apify %s: %d registros", nome, n)
        except Exception as e:
            log.warning("Apify falhou [%s]: %s", nome, e)
    return itens


# ----------------------------------------------------------------- enriquecimento (texto completo + imagem)
def resolver_google(url):
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url, interval=0.3)
        if res.get("status") or res.get("success"):
            return res.get("decoded_url") or url
    except Exception as e:
        log.debug("Decodificação Google falhou: %s", e)
    return url


def enriquecer(item):
    """Abre a página para obter link real, imagem (og:image) e texto principal."""
    if item["tipo"] in ("video", "social"):
        return item
    try:
        url = resolver_google(item["url"])
        r = _get(url, timeout=20, allow_redirects=True)
        item["url"] = r.url
        soup = BeautifulSoup(r.text, "html.parser")
        if not item.get("imagem"):
            for prop in ("og:image", "twitter:image", "og:image:url"):
                tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if tag and tag.get("content"):
                    item["imagem"] = urljoin(r.url, tag["content"])
                    break
        if not item.get("publicado"):
            tag = soup.find("meta", attrs={"property": "article:published_time"})
            if tag and tag.get("content"):
                item["publicado"] = para_iso(tag["content"])
        def _texto(no):
            return " ".join(p for p in (x.get_text(" ", strip=True) for x in no.find_all("p")) if len(p) > 40)
        texto = _texto(soup.find("article") or soup)
        if len(texto) < 400:
            texto = _texto(soup)
        desc = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            texto = desc["content"].strip() + " | " + texto
        if len(texto) > len(item.get("texto", "")):
            item["texto"] = texto[:4000]
    except Exception as e:
        log.debug("Enriquecimento falhou [%s]: %s", item["url"], e)
    return item
