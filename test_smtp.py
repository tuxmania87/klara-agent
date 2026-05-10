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
SMTP_PORT     = 465
SMTP_USER     = "mail@klarabelle.de"
SMTP_PASSWORD = "DEIN_PASSWORT_HIER"

TO            = "klara@keinerspieltmitmir.de"
SUBJECT       = "SMTP Alias Test"

# ── Verschiedene Varianten ────────────────────────────────────────────────────

async def test_variant(name: str, from_header: str, envelope_sender: str | None = None):
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"  From-Header:      {from_header}")
    print(f"  Envelope-Sender:  {envelope_sender or '(aus From-Header)'}")

    msg = MIMEText(f"Test-Variante: {name}\nFrom-Header: {from_header}\nEnvelope: {envelope_sender or 'abgeleitet'}", "plain", "utf-8")
    msg["Subject"] = f"{SUBJECT} — {name}"
    msg["From"]    = from_header
    msg["To"]      = TO

    tls_context = ssl.create_default_context()

    try:
        smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT, use_tls=True, tls_context=tls_context)
        await smtp.connect()
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
    # Variante 1: From = Alias, kein expliziter Envelope
    await test_variant(
        "Alias im From, kein Envelope",
        from_header="mail@klarahartmann.de",
        envelope_sender=None,
    )

    # Variante 2: From = Alias, Envelope = konfigurierter Account
    await test_variant(
        "Alias im From, Envelope = klarabelle",
        from_header="mail@klarahartmann.de",
        envelope_sender="mail@klarabelle.de",
    )

    # Variante 3: From = Alias mit Display Name
    await test_variant(
        "Alias mit Display Name",
        from_header="Klara Hartmann <mail@klarahartmann.de>",
        envelope_sender=None,
    )

    # Variante 4: From = konfigurierter Account (Baseline — muss funktionieren)
    await test_variant(
        "Baseline: konfigurierter Account",
        from_header="mail@klarabelle.de",
        envelope_sender=None,
    )


asyncio.run(main())
