"""
Shared email template helpers for girolavoro notifications.

All templates share the same header/footer structure:
  - Dark header with girolavoro logo + yellow underline
  - Content area
  - Footer with unsubscribe hint + Facebook/Instagram icon-buttons

Social links are currently placeholders — replace with real URLs when available.
"""

FACEBOOK_URL = "https://www.facebook.com/profile.php?id=61583756255378&locale=it_IT"
INSTAGRAM_URL = "https://www.instagram.com/girolavoro"

def _social_footer_html(fb_src="cid:fb-icon", ig_src="cid:ig-icon"):
    """Returns the HTML block for the social media footer buttons."""
    return f"""
          <!-- Social -->
          <tr>
            <td style="padding:16px 40px 0;text-align:center;">
              <a href="{FACEBOOK_URL}" target="_blank" rel="noopener"
                 style="display:inline-block;margin:0 8px;text-decoration:none;">
                <img src="{fb_src}" width="32" height="32" alt="Facebook" style="display:block;border:0;" />
              </a>
              <a href="{INSTAGRAM_URL}" target="_blank" rel="noopener"
                 style="display:inline-block;margin:0 8px;text-decoration:none;">
                <img src="{ig_src}" width="32" height="32" alt="Instagram" style="display:block;border:0;" />
              </a>
            </td>
          </tr>"""


def _header_html(logo_src="cid:girolavoro-logo"):
    return f"""
          <!-- Header -->
          <tr>
            <td style="background-color:#0a0e1a;padding:32px 40px;text-align:center;">
              <img src="{logo_src}" alt="girolavoro"
                   width="140" style="display:block;margin:0 auto;color:#f5b731;font-size:26px;font-weight:bold;font-family:Arial,sans-serif;letter-spacing:2px;" />
              <div style="width:40px;height:3px;background-color:#f5b731;margin:16px auto 0;"></div>
            </td>
          </tr>"""


def _footer_html(include_unsubscribe: bool = True, extra_note: str = "") -> str:
    unsubscribe_note = (
        '<p style="color:#aaaaaa;margin:4px 0 0;font-size:11px;">'
        'Per non ricevere più queste email, aggiorna le preferenze di notifica nell\'app girolavoro.'
        '</p>'
        if include_unsubscribe else ""
    )
    extra = f'<p style="color:#aaaaaa;margin:4px 0 0;font-size:11px;">{extra_note}</p>' if extra_note else ""
    return f"""
          <!-- Footer -->
          <tr>
            <td style="background-color:#f8f8fc;padding:20px 40px 16px;text-align:center;border-top:1px solid #eeeeee;">
              <p style="color:#aaaaaa;margin:0;font-size:12px;">&copy; 2026 girolavoro &mdash; Tutti i diritti riservati</p>
              {unsubscribe_note}
              {extra}
            </td>
          </tr>"""


def _wrap(
    inner_rows: str,
    include_unsubscribe: bool = True,
    extra_note: str = "",
    logo_src: str = "cid:girolavoro-logo",
    fb_src: str = "cid:fb-icon",
    ig_src: str = "cid:ig-icon",
) -> str:
    """Wraps content rows with the standard girolavoro email shell.

    Pass ``logo_src``, ``fb_src``, ``ig_src`` as base64 data URIs or HTTPS URLs
    when CID attachments are not available (e.g. Cognito emails).
    """
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
         style="background-color:#f4f4f4;padding:40px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0"
               style="background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
          {_header_html(logo_src)}
          {inner_rows}
          {_social_footer_html(fb_src, ig_src)}
          {_footer_html(include_unsubscribe, extra_note)}
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ── Template builders ──────────────────────────────────────────────────────────

def build_app_update_email(version: str, notes_html: str) -> tuple[str, str]:
    """Returns (subject, html_body) for an app-update broadcast email."""
    subject = f"Novità su girolavoro — versione {version}"
    inner = f"""
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="color:#0a0e1a;margin:0 0 8px;font-size:22px;font-weight:700;">
                Abbiamo aggiornato l'app! 🎉
              </h2>
              <p style="color:#555555;margin:0 0 20px;font-size:15px;line-height:1.6;">
                Una nuova versione di girolavoro è disponibile. Aggiorna subito per scoprire
                tutte le novità:
              </p>
              <div style="background-color:#fffbeb;border-left:4px solid #f5b731;
                          padding:16px 20px;border-radius:4px;margin-bottom:24px;">
                {notes_html}
              </div>
              </td>
          </tr>"""
    return subject, _wrap(inner, include_unsubscribe=False)


def build_upgrade_reminder_email(first_name: str) -> tuple[str, str]:
    """Returns (subject, html_body) for upgrade-to-premium reminder."""
    subject = "Sblocca tutto con girolavoro 🚀"
    inner = f"""
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="color:#0a0e1a;margin:0 0 16px;font-size:22px;font-weight:700;">
                Ciao {first_name or ""}! Potresti fare molto di più!
              </h2>
              <p style="color:#555555;margin:0 0 16px;font-size:15px;line-height:1.6;">
                Con il profilo <strong>girolavoro verificato</strong> puoi iniziare a pubblicare le tue offerte di lavoro 
                o a cercare il tuo prossimo impiego!
              </p>
              <p style="color:#555555;margin:0 0 16px;font-size:15px;line-height:1.6;">
                Non restare ad aspettare! Inizia a cercare, con <strong>girolavoro</strong>!
              </p>
            </td>
          </tr>"""
    return subject, _wrap(inner)


def build_company_no_listing_email(first_name: str) -> tuple[str, str]:
    """Returns (subject, html_body) per company che non ha ancora creato annunci."""
    subject = "Il tuo team ti aspetta — crea il tuo primo annuncio su girolavoro"
    inner = f"""
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="color:#0a0e1a;margin:0 0 16px;font-size:22px;font-weight:700;">
                Ciao {first_name or ""}! Sei pronto a trovare il tuo team? 
              </h2>
              <p style="color:#555555;margin:0 0 16px;font-size:15px;line-height:1.6;">
                Il tuo account aziendale è attivo, ma non hai ancora pubblicato nessun
                annuncio di lavoro. In pochi minuti puoi raggiungere migliaia di lavoratori
                qualificati.
              </p>
              <p style="color:#555555;margin:0 0 24px;font-size:15px;line-height:1.6;">
                Crea il tuo primo annuncio ora: scegli il ruolo, imposta date e compenso,
                e inizia a ricevere candidature subito.
              </p>
            </td>
          </tr>"""
    return subject, _wrap(inner)


def build_worker_no_application_email(first_name: str) -> tuple[str, str]:
    """Returns (subject, html_body) per worker che non ha ancora applicato."""
    subject = "Ci sono offerte che ti aspettano su girolavoro 👀"
    inner = f"""
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="color:#0a0e1a;margin:0 0 16px;font-size:22px;font-weight:700;">
                Ciao {first_name or ""}! Le opportunità non aspettano!
              </h2>
              <p style="color:#555555;margin:0 0 16px;font-size:15px;line-height:1.6;">
                Non hai ancora inviato nessuna candidatura su girolavoro. Le aziende
                pubblicano nuovi annunci ogni giorno — potresti perderteli!
              </p>
              <p style="color:#555555;margin:0 0 24px;font-size:15px;line-height:1.6;">
                Esplora le offerte di lavoro disponibili e candidati
                subito al ruolo che fa per te, nel posto che vuoi tu.
              </p>
            </td>
          </tr>"""
    return subject, _wrap(inner)
