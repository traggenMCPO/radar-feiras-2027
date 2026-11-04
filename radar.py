"""
RADAR DE EXPOSITORES - FEIRAS AGRO 2027
Executa uma rodada completa: coleta -> filtra -> analisa com Claude -> atualiza página -> notifica por e-mail.
Agendado a cada 30 min pelo GitHub Actions (.github/workflows/radar.yml), mas também roda local:
    python radar.py              (rodada normal)
    python radar.py --sem-ia     (testa só a coleta, sem gastar API)
"""
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import fontes
from analise import analisar
from notificacao import enviar_email
from pagina import gerar_pagina

RAIZ = Path(__file__).parent
DADOS = RAIZ / "data"
ARQ_ESTADO = DADOS / "estado.json"
ARQ_ITENS = DADOS / "itens.json"
PAGINA = RAIZ / "docs" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radar")

try:
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env")
except ImportError:
    pass


def ler_json(caminho, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def salvar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def passa_prefiltro(item, aliases, limite):
    texto = fontes.normalizar(f'{item["titulo"]} {item["texto"]} {item["url"]}')
    if not any(a in texto for a in aliases):
        return False
    if item.get("publicado"):
        try:
            if datetime.fromisoformat(item["publicado"]) < limite:
                return False
        except ValueError:
            pass
    return True


def main():
    sem_ia = "--sem-ia" in sys.argv
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    estado = ler_json(ARQ_ESTADO, {})
    vistos = estado.setdefault("vistos", {})
    itens_salvos = ler_json(ARQ_ITENS, [])
    agora = datetime.now(timezone.utc)

    # ---------------- 1. COLETA
    coleta = []
    etapas = []
    if cfg.get("google_news", True):
        etapas.append(("Google News", lambda: fontes.coletar_google_news(cfg)))
    if cfg.get("bing_news", True):
        etapas.append(("Bing News", lambda: fontes.coletar_bing(cfg)))
    etapas += [
        ("Portais RSS", lambda: fontes.coletar_rss(cfg)),
        ("Sites oficiais", lambda: fontes.coletar_sites(cfg)),
        ("YouTube", lambda: fontes.coletar_youtube(cfg, estado, os.getenv("YOUTUBE_API_KEY"))),
        ("Apify (redes sociais)", lambda: fontes.coletar_apify(cfg, estado, os.getenv("APIFY_TOKEN"))),
    ]
    resumo_fontes = {}
    for nome, func in etapas:
        try:
            r = func()
        except Exception as e:
            log.exception("Etapa %s falhou: %s", nome, e)
            r = []
        resumo_fontes[nome] = len(r)
        log.info("%-22s %4d itens", nome, len(r))
        coleta.extend(r)

    # ---------------- 2. DEDUPLICAÇÃO + PRÉ-FILTRO
    aliases = sorted({fontes.normalizar(a) for f in cfg["feiras"] for a in f["aliases"] + [f["nome"]]})
    limite = agora - timedelta(days=cfg.get("janela_dias", 45))
    unicos, titulos = {}, set()
    for it in coleta:
        if not it["url"] or it["id"] in vistos or it["id"] in unicos:
            continue
        chave_titulo = fontes.normalizar(it["titulo"])[:90]
        if chave_titulo and chave_titulo in titulos:
            vistos[it["id"]] = agora.isoformat()
            continue
        titulos.add(chave_titulo)
        unicos[it["id"]] = it
    candidatos = []
    for it in unicos.values():
        if passa_prefiltro(it, aliases, limite):
            candidatos.append(it)
        else:
            vistos[it["id"]] = agora.isoformat()
    log.info("Novos únicos: %d | candidatos após pré-filtro: %d", len(unicos), len(candidatos))

    maximo = cfg.get("claude", {}).get("max_itens_por_execucao", 80)
    candidatos.sort(key=lambda x: x.get("publicado") or "", reverse=True)
    lote, adiados = candidatos[:maximo], candidatos[maximo:]
    if adiados:
        log.info("%d candidatos adiados para a próxima rodada (limite de custo)", len(adiados))

    if sem_ia:
        for it in lote[:40]:
            print(f'- [{it["rede"]}] {it["titulo"][:100]}  ->  {it["url"][:90]}')
        log.info("Modo --sem-ia: nada foi salvo.")
        return

    # ---------------- 3. ENRIQUECIMENTO + ANÁLISE IA
    with ThreadPoolExecutor(max_workers=8) as ex:
        lote = list(ex.map(fontes.enriquecer, lote))
    chave = os.getenv("ANTHROPIC_API_KEY")
    if not chave:
        log.error("ANTHROPIC_API_KEY não definida - análise impossível.")
        return
    analisados = analisar(lote, cfg, chave)

    novos = []
    urls_salvas = {fontes.url_canonica(d["url"]) for d in itens_salvos}
    for it in analisados:
        if it.get("_falhou"):
            continue  # tenta de novo na próxima rodada
        vistos[it["id"]] = agora.isoformat()
        if it.get("relevante") and fontes.url_canonica(it["url"]) not in urls_salvas:
            it["encontrado_em"] = agora.isoformat()
            it.pop("texto", None)
            novos.append(it)
            urls_salvas.add(fontes.url_canonica(it["url"]))
    log.info("Sinais relevantes novos: %d", len(novos))

    # ---------------- 4. PERSISTÊNCIA + PÁGINA
    itens_salvos = (novos + itens_salvos)[:3000]
    corte = (agora - timedelta(days=120)).isoformat()
    estado["vistos"] = {k: v for k, v in vistos.items() if v >= corte}
    estado["ultima_execucao"] = {"quando": agora.isoformat(), "fontes": resumo_fontes,
                                 "candidatos": len(candidatos), "novos": len(novos)}
    salvar_json(ARQ_ITENS, itens_salvos)
    salvar_json(ARQ_ESTADO, estado)
    gerar_pagina(itens_salvos, cfg, PAGINA)

    # ---------------- 5. NOTIFICAÇÃO
    ncfg = cfg.get("notificacao", {})
    notificar = [d for d in novos if d.get("confianca", 0) >= ncfg.get("confianca_minima_email", 0)]
    if notificar or ncfg.get("enviar_email_sem_novidades"):
        enviar_email(notificar, cfg)


if __name__ == "__main__":
    main()

