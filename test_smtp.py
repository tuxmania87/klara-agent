"""
Minimaler SMTP-Test für Mailcow Alias-Domain Absender.
Direkt ausführen: python3 test_smtp.py
Liest Credentials aus .env
"""
import asyncio
import ssl
import aiosmtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os

load_dotenv()

# ── Konfiguration aus .env ────────────────────────────────────────────────────
SMTP_HOST     = os.getenv("MAILCOW_IMAP_HOST", "mx.klarabelle.de")
SMTP_USER     = os.getenv("MAILCOW_EMAIL_ADDRESS", "mail@klarabelle.de")
SMTP_PASSWORD = os.getenv("MAILCOW_SMTP_PASSWORD", "")

TO            = "klara@keinerspieltmitmir.de"
SUBJECT       = "SMTP Alias Test"

if not SMTP_PASSWORD:
    print("❌ MAILCOW_SMTP_PASSWORD nicht in .env gesetzt!")
    exit(1)

print(f"SMTP Host: {SMTP_HOST}")
print(f"SMTP User: {SMTP_USER}")
print(f"Sende an:  {TO}")


async def test_variant(name: str, from_header: str, port: int, use_tls: bool, envelope_sender: str | None = None):
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"  Port:             {port} ({'implicit TLS' if use_tls else 'STARTTLS'})")
    print(f"  From-Header:      {from_header}")
    print(f"  Envelope-Sender:  {envelope_sender or '(aus From-Header)'}")

    from email.utils import make_msgid
    from_domain = from_header.split("@")[-1].rstrip(">") if "@" in from_header else SMTP_HOST

    msg = MIMEText(f"Test: {name}", "plain", "utf-8")
    msg["Subject"]    = f"{SUBJECT} — {name}"
    msg["From"]       = from_header
    msg["To"]         = TO
    msg["Message-ID"] = make_msgid(domain=from_domain)

    tls_context = ssl.create_default_context()

    try:
        if use_tls:
            smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=port, use_tls=True,
                                   tls_context=tls_context)
            await smtp.connect()
        else:
            smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=port, use_tls=False)
            await smtp.connect()
            await smtp.starttls(tls_context=tls_context)

        await smtp.login(SMTP_USER, SMTP_PASSWORD)

        if envelope_sender:
            await smtp.send_message(msg, sender=envelope_sender)
        else:
            await smtp.send_message(msg, sender=from_header)

        await smtp.quit()
        print(f"  ✅ ERFOLG")
    except Exception as e:
        print(f"  ❌ FEHLER: {e}")


async def main():
    variants = [
        # Port 587 implicit TLS (Mailcow-Variante)
        ("587 implicit TLS, Alias From",             "mail@klarahartmann.de",                  587, True,  None),
        ("587 implicit TLS, Alias Envelope",         "mail@klarahartmann.de",                  587, True,  "mail@klarahartmann.de"),
        ("587 implicit TLS, Baseline",               "mail@klarabelle.de",                     587, True,  None),
        # Port 465 implicit TLS
        ("465 TLS, Alias From",                      "mail@klarahartmann.de",                  465, True,  None),
        ("465 TLS, Alias Envelope",                  "mail@klarahartmann.de",                  465, True,  "mail@klarahartmann.de"),
        ("465 TLS, Baseline",                        "mail@klarabelle.de",                     465, True,  None),
    ]

    for name, from_header, port, use_tls, envelope in variants:
        await test_variant(name, from_header, port, use_tls, envelope)


asyncio.run(main())
