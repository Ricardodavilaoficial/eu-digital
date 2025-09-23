# services/email_sender.py
import os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, FileSystemLoader, select_autoescape

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "mei-robo@fujicadobrasil.com.br")  # ← trocável no Render

# Diretório dos templates Jinja (pasta templates/emails)
env = Environment(
    loader=FileSystemLoader(searchpath=os.path.join(os.getcwd(), "templates")),
    autoescape=select_autoescape(["html"])
)

def _render(template_name: str, context: dict) -> str:
    tpl = env.get_template(f"emails/{template_name}.html")
    return tpl.render(**context)

def _send_html(to_email: str, subject: str, html: str, sender: str = None):
    sender = sender or SENDER_EMAIL
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(sender, [to_email], msg.as_string())

def send_daily_summary(to_email: str, date_str: str, kpis: dict, rows: list, include_tomorrow=False):
    subject = f"Agenda de hoje – {date_str}"
    html = _render("daily_summary", {
        "sender": SENDER_EMAIL,
        "date_str": date_str,
        "kpis": kpis,
        "rows": rows,
        "include_tomorrow": include_tomorrow
    })
    _send_html(to_email, subject, html)

def send_confirmation(to_email: str, data: dict):
    # data espera: {"data":"09/09", "hora":"14:00", "nome":"João", "links":{"confirmar":"...", "reagendar":"...", "cancelar":"..."}}
    subject = f"Confirmação do seu horário – {data.get('data')} {data.get('hora')}"
    html = _render("confirmation", {"sender": SENDER_EMAIL, **data})
    _send_html(to_email, subject, html)

def send_reminder(to_email: str, data: dict):
    # data espera: {"data":"09/09", "hora":"14:00", "nome":"João", "link":"..."}
    subject = f"Lembrete: seu horário é hoje às {data.get('hora')}"
    html = _render("reminder", {"sender": SENDER_EMAIL, **data})
    _send_html(to_email, subject, html)
