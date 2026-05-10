"""
Minimaler SMTP-Test für Mailcow Alias-Domain Absender.
Direkt ausführen: python3 test_smtp.py
"""
import asyncio
import ssl
import aiosmtplib
from email.mime.text import MIMEText

# ── Konfiguration ─────────────────────────────────────────────────────────────
SMTP_HOST     = "mx.klarabelle.de"
SMTP_USER     = "mail@klarabelle.de"
SMTP_PASSWORD = "DEIN_PASSWORT_HIER"

TO            = "klara@keinerspieltmitmir.de"
SUBJECT       = "SMTP Alias Test"


async def test_variant(name: str, from_header: str, port: int, use_tls: bool, envelope_sender: str | None = None):
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"  Port:             {port} ({'implicit TLS' if use_tls else 'STARTTLS'})")
    print(f"  From-Header:      {from_header}")
    print(f"  Envelope-Sender:  {envelope_sender or '(aus From-Header)'}")

    msg = MIMEText(f"Test: {name}", "plain", "utf-8")
    msg["Subject"] = f"{SUBJECT} — {name}"
    msg["From"]    = from_header
    msg["To"]      = TO

    tls_context = ssl.create_default_context()

    try:
        if use_tls:
            smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=port, use_tls=True, tls_context=tls_context)
            await smtp.connect()
        else:
            smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=port, use_tls=False)
            await smtp.connect()
            await smtp.starttls(tls_context=tls_context)

        await smtp.login(SMTP_USER, SMTP_PASSWORD)

        if envelope_sender:
            await smtp.send_message(msg, sender=envelope_sender)
        else:
            await smtp.send_message(msg)

        await smtp.quit()
        print(f"  ✅ ERFOLG")
    except Exception as e:
        print(f"  ❌ FEHLER: {e}")


async def main():
    variants = [
        # Port 587 STARTTLS (wie Rainloop) — Alias ohne expliziten Envelope
        ("587 STARTTLS, Alias From, kein Envelope",      "mail@klarahartmann.de",                587, False, None),
        # Port 587 STARTTLS — Alias mit explizitem Envelope
        ("587 STARTTLS, Alias From, Alias Envelope",     "mail@klarahartmann.de",                587, False, "mail@klarahartmann.de"),
        # Port 587 STARTTLS — Display Name
        ("587 STARTTLS, Display Name",                   "Klara Hartmann <mail@klarahartmann.de>", 587, False, "mail@klarahartmann.de"),
        # Port 465 implicit TLS — Alias (bisheriger Code)
        ("465 TLS, Alias From, kein Envelope",           "mail@klarahartmann.de",                465, True,  None),
        # Baseline Port 465 — konfigurierter Account
        ("465 TLS, Baseline klarabelle",                 "mail@klarabelle.de",                   465, True,  None),
    ]

    for name, from_header, port, use_tls, envelope in variants:
        await test_variant(name, from_header, port, use_tls, envelope)


asyncio.run(main())
