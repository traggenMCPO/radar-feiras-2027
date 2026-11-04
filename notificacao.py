"""Notificação por e-mail (SMTP). Funciona com Gmail (senha de app), Outlook.com, SendGrid, etc."""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

log = logging.getLogger("radar")

CORES = {"Confirmada": "#1b8a3a", "Provável": "#62a83a", "Especulação": "#e09b00",
         "Em avaliação": "#3b7dd8", "Não participará": "#c62828", "Indefinida": "#8a8f8b"}


def _card(d):
    img = (f'<img src="{escape(d["imagem"])}" width="120" style="border-radius:6px;object-fit:cover;max-height:80px">'
           if d.get("imagem") else "")
    tags = " · ".join(escape(x) for x in (d.get("feiras") or []) + (d.get("empresas") or []))
    return f"""
    <tr><td style="padding:12px 0;border-bottom:1px solid #e5e5e5">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td width="130" valign="top">{img}</td>
        <td valign="top" style="font-family:Arial,sans-serif">
          <span style="background:{CORES.get(d.get('intencao'), '#888')};color:#fff;font-size:11px;padding:2px 8px;border-radius:10px">
            {escape(d.get('intencao', ''))} · {d.get('confianca', 0)}%</span>
          <span style="font-size:11px;color:#666"> {escape(d.get('segmento', ''))} · {escape(d.get('rede', ''))}</span><br>
          <a href="{escape(d['url'])}" style="font-size:15px;font-weight:bold;color:#1f6f3f;text-decoration:none">
            {escape(d.get('titulo_ia') or d['titulo'])}</a>
          <p style="margin:4px 0;font-size:13px;color:#333">{escape(d.get('resumo', ''))}</p>
          <span style="font-size:11px;color:#8a5a00">{tags}</span>
        </td></tr></table>
    </td></tr>"""


def enviar_email(novos, cfg):
    host, usuario, senha = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    destino = os.getenv("EMAIL_TO")
    if not all([host, usuario, senha, destino]):
        log.warning("E-mail não configurado (SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_TO). Notificação ignorada.")
        return False
    porta = int(os.getenv("SMTP_PORT", "587"))
    remetente = os.getenv("EMAIL_FROM", usuario)

    if novos:
        confirmados = sum(1 for d in novos if d.get("intencao") == "Confirmada")
        desist = sum(1 for d in novos if d.get("intencao") == "Não participará")
        assunto = f"🌾 Radar Feiras {cfg['ano_alvo']}: {len(novos)} novo(s) sinal(is)"
        if confirmados or desist:
            assunto += f" · {confirmados} confirmação(ões) · {desist} desistência(s)"
        linhas = "".join(_card(d) for d in sorted(novos, key=lambda x: -x.get("confianca", 0)))
    else:
        assunto = f"Radar Feiras {cfg['ano_alvo']}: sem novidades nesta rodada"
        linhas = '<tr><td style="font-family:Arial">Nenhum novo sinal encontrado nesta rodada.</td></tr>'

    html = f"""<html><body style="background:#f4f6f3;padding:16px">
      <table width="100%" style="max-width:680px;margin:auto;background:#fff;border-radius:10px;padding:16px">
        <tr><td style="font-family:Arial;font-size:20px;font-weight:bold;color:#1f6f3f">Radar de Expositores · Feiras Agro {cfg['ano_alvo']}</td></tr>
        {linhas}
        <tr><td style="padding-top:14px;font-family:Arial"><a href="{escape(cfg.get('url_pagina', ''))}"
          style="background:#1f6f3f;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Abrir painel completo</a></td></tr>
      </table></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = assunto, remetente, destino
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        if porta == 465:
            srv = smtplib.SMTP_SSL(host, porta, timeout=30)
        else:
            srv = smtplib.SMTP(host, porta, timeout=30)
            srv.starttls()
        srv.login(usuario, senha)
        srv.sendmail(remetente, [e.strip() for e in destino.split(",")], msg.as_string())
        srv.quit()
        log.info("E-mail enviado para %s", destino)
        return True
    except Exception as e:
        log.error("Falha ao enviar e-mail: %s", e)
        return False

