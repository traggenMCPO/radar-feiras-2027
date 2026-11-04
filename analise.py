"""Análise com Claude: filtra relevância, identifica empresas, feiras, segmento e intenção de participação."""
import json
import logging
import re

log = logging.getLogger("radar")

INTENCOES = ["Confirmada", "Provável", "Especulação", "Em avaliação", "Não participará", "Indefinida"]

SISTEMA = """Você é analista sênior de inteligência de mercado do agronegócio brasileiro.
Sua tarefa: avaliar conteúdos da internet (notícias, posts, vídeos, páginas) e identificar sinais sobre
EMPRESAS EXPOSITORAS (máquinas, implementos, sementes, fertilizantes, defensivos, biológicos, tecnologia,
irrigação, armazenagem, pecuária, bancos/crédito etc.) e sua INTENÇÃO de participar ou não das feiras
agropecuárias brasileiras na edição de {ano}.

Considere RELEVANTE quando o conteúdo trouxer pelo menos um destes sinais:
- empresa confirma, planeja, avalia, reduz, amplia ou cancela presença/estande em feira de {ano} (ou "próxima edição", quando a próxima for {ano});
- especulação, rumor ou análise de mercado sobre participação de expositores em {ano};
- organização da feira divulga venda de espaços, lista/número de expositores, renovações, desistências ou novidades para {ano};
- balanço da edição atual com declarações de empresas sobre voltar (ou não) na próxima edição;
- lançamentos de produtos programados para feiras de {ano}.
Considere NÃO relevante: conteúdo sem relação com participação de expositores, notícias genéricas do agro,
shows/eventos culturais, resultados apenas de edições passadas sem nenhuma menção à próxima edição.

Segmentos permitidos (use exatamente um): {segmentos}
Intenções permitidas (use exatamente uma): {intencoes}
Feiras conhecidas: {feiras}

Responda SOMENTE com JSON válido, sem texto antes ou depois, no formato:
{{"itens": [{{"idx": 0, "relevante": true, "empresas": ["Nome"], "feiras": ["Nome da feira"],
"segmento": "...", "intencao": "...", "confianca": 0-100,
"titulo": "título curto em português", "resumo": "2 a 3 frases objetivas em português explicando o sinal encontrado"}}]}}
Para itens não relevantes, devolva apenas {{"idx": N, "relevante": false}}."""


def _extrair_json(txt: str):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("Resposta sem JSON")
    return json.loads(m.group(0))


def analisar(itens, cfg, api_key):
    if not itens:
        return []
    import anthropic

    cliente = anthropic.Anthropic(api_key=api_key)
    ccfg = cfg.get("claude", {})
    modelo = ccfg.get("modelo", "claude-haiku-4-5")
    lote = ccfg.get("itens_por_lote", 8)
    sistema = SISTEMA.format(
        ano=cfg["ano_alvo"],
        segmentos=" | ".join(cfg["segmentos"]),
        intencoes=" | ".join(INTENCOES),
        feiras=", ".join(f["nome"] for f in cfg["feiras"]),
    )

    resultados = []
    for i in range(0, len(itens), lote):
        grupo = itens[i:i + lote]
        entrada = [{
            "idx": j, "rede": it["rede"], "fonte": it["fonte"], "publicado": it.get("publicado"),
            "titulo": it["titulo"], "texto": (it.get("texto") or "")[:2500], "url": it["url"],
        } for j, it in enumerate(grupo)]
        prompt = "Analise os conteúdos abaixo:\n" + json.dumps(entrada, ensure_ascii=False)
        dados = None
        for tentativa in range(2):
            try:
                resp = cliente.messages.create(
                    model=modelo, max_tokens=4000, system=sistema,
                    messages=[{"role": "user", "content": prompt}],
                )
                dados = _extrair_json("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
                break
            except Exception as e:
                log.warning("Claude falhou (lote %d, tentativa %d): %s", i // lote, tentativa + 1, e)
        if dados is None:
            for it in grupo:
                it["_falhou"] = True
            continue
        por_idx = {d.get("idx"): d for d in dados.get("itens", []) if isinstance(d, dict)}
        for j, it in enumerate(grupo):
            d = por_idx.get(j, {"relevante": False})
            it["relevante"] = bool(d.get("relevante"))
            if it["relevante"]:
                seg = d.get("segmento") if d.get("segmento") in cfg["segmentos"] else "Outros"
                it.update({
                    "empresas": d.get("empresas") or [],
                    "feiras": d.get("feiras") or [],
                    "segmento": seg,
                    "intencao": d.get("intencao") if d.get("intencao") in INTENCOES else "Indefinida",
                    "confianca": int(d.get("confianca") or 0),
                    "titulo_ia": d.get("titulo") or it["titulo"],
                    "resumo": d.get("resumo") or "",
                })
            resultados.append(it)
    return resultados

