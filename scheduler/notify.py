"""Sends the briefing link to Telegram and email."""
from __future__ import annotations

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests


class NotifyError(Exception):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise NotifyError(f"Missing setting {name}. Add it to GitHub Secrets (or your .env file).")
    return value


def send_telegram(item: dict) -> None:
    token, chat_id = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    e = html.escape

    if item["kind"] == "failure":
        text = f"⚠️ <b>{e(item['name'])}</b> could not be created today.\n\n{e(item['error'])}"
    else:
        lines = [f"☀️ <b>{e(item['name'])}</b>", f"<i>{e(item['date_label'])}</i>", ""]
        if item.get("title"):
            lines += [f"<b>{e(item['title'])}</b>", ""]
        if item.get("highlights"):
            lines.append("<b>Top 3 today:</b>")
            lines += [f"{i}. {e(h)}" for i, h in enumerate(item["highlights"], 1)]
            lines.append("")
        if item.get("mood"):
            lines += [f"📊 {e(item['mood'])}", ""]
        lines.append(f'👉 <a href="{e(item["url"])}">Read the full briefing</a>')
        text = "\n".join(lines)

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"},
        timeout=30,
    )
    if not resp.ok:
        raise NotifyError(f"Telegram error {resp.status_code}: {resp.text[:300]}")


def _email_html(item: dict) -> str:
    e = html.escape
    if item["kind"] == "failure":
        return f"<p>⚠️ <b>{e(item['name'])}</b> could not be created today.</p><p>{e(item['error'])}</p>"

    highlights = "".join(f"<li style='margin:6px 0'>{e(h)}</li>" for h in item.get("highlights", []))
    mood = f"<p style='color:#444'>📊 {e(item['mood'])}</p>" if item.get("mood") else ""
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:auto;color:#1d1d1f;line-height:1.6">
  <p style="color:#6b6b70;margin:0">{e(item['date_label'])}</p>
  <h2 style="margin:4px 0 16px">{e(item.get('title') or item['name'])}</h2>
  {"<p><b>Top 3 today:</b></p><ol>" + highlights + "</ol>" if highlights else ""}
  {mood}
  <p style="margin:28px 0">
    <a href="{e(item['url'])}" style="background:#0b6e4f;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">
      Read the full briefing →</a>
  </p>
  <p style="color:#6b6b70;font-size:13px">{e(item['name'])} · sent by your Daily Scheduler</p>
</div>"""


def send_email(item: dict) -> None:
    sender, password = _env("EMAIL_ADDRESS"), _env("EMAIL_APP_PASSWORD")
    recipients = [r.strip() for r in os.environ.get("EMAIL_TO", sender).split(",") if r.strip()]
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))

    if item["kind"] == "failure":
        subject = f"⚠️ {item['name']} failed today"
        plain = f"{item['name']} could not be created today.\n\n{item['error']}"
    else:
        subject = f"{item['name']}: {item.get('title') or item['date_label']}"
        plain = "\n".join(
            [item["date_label"], ""] + [f"- {h}" for h in item.get("highlights", [])]
            + ["", item.get("mood", ""), "", f"Read the full briefing: {item['url']}"]
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(recipients)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(_email_html(item), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, recipients, msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"Email error: {exc}") from exc


SENDERS = {"telegram": send_telegram, "email": send_email}
