import boto3
import sys
sys.path.append('src/lambdas/services/email-notifications')
from shared.email_templates import _wrap

# ── S3 public HTTPS URLs (uploaded once via scripts/upload-email-images.ps1) ─
# The companies-assets buckets have PublicReadGetObject — images load in any
# email client without hitting the Cognito 20 000-char HTML limit.
_S3_BASE = "https://{bucket}.s3.eu-south-1.amazonaws.com/email"

_URLS = {
    # pool_id → (logo_src, fb_src, ig_src)
    "eu-south-1_0oK9agPYd": (              # DEV
        f"{_S3_BASE.format(bucket='beezey-dev-companies-assets')}/beebusy-logo.png",
        f"{_S3_BASE.format(bucket='beezey-dev-companies-assets')}/fb-icon.png",
        f"{_S3_BASE.format(bucket='beezey-dev-companies-assets')}/ig-icon.png",
    ),
    "eu-south-1_1uXj751D4": (              # DEV-BE
        f"{_S3_BASE.format(bucket='beezey-dev-be-companies-assets')}/beebusy-logo.png",
        f"{_S3_BASE.format(bucket='beezey-dev-be-companies-assets')}/fb-icon.png",
        f"{_S3_BASE.format(bucket='beezey-dev-be-companies-assets')}/ig-icon.png",
    ),
    "eu-south-1_iCBtUlJO6": (              # PROD
        f"{_S3_BASE.format(bucket='beezey-prod-companies-assets')}/beebusy-logo.png",
        f"{_S3_BASE.format(bucket='beezey-prod-companies-assets')}/fb-icon.png",
        f"{_S3_BASE.format(bucket='beezey-prod-companies-assets')}/ig-icon.png",
    ),
}

# The inner message for Cognito
cognito_inner = """
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="color:#0a0e1a;margin:0 0 16px;font-size:22px;font-weight:700;">
                Benvenuto su girolavoro!
              </h2>
              <p style="color:#555555;margin:0 0 16px;font-size:15px;line-height:1.6;">
                Grazie per esserti registrato. Per completare la creazione del tuo 
                account, usa il seguente codice di verifica nell'app:
              </p>
              <div style="background-color:#fffbeb;border-left:4px solid #f5b731;
                          padding:16px 20px;border-radius:4px;margin-bottom:24px;
                          text-align:center;font-size:32px;font-weight:bold;letter-spacing:4px;color:#000;">
                {####}
              </div>
              <p style="color:#aaaaaa;margin:0;font-size:13px;line-height:1.6;">
                Se non hai richiesto questo codice, puoi ignorare l'email.
              </p>
            </td>
          </tr>
"""

# Include unsubscribe=False because it's a transactional OTP email.
# html_body is built per-pool inside update_pool() to use the right S3 bucket.

client = boto3.client('cognito-idp', region_name='eu-south-1')

def update_pool(pool_id):
    print(f"[{pool_id}] Recupero settings attuali...")
    try:
        logo_src, fb_src, ig_src = _URLS[pool_id]
        html_body = _wrap(
            cognito_inner,
            include_unsubscribe=False,
            logo_src=logo_src,
            fb_src=fb_src,
            ig_src=ig_src,
        )
        print(f"[{pool_id}] HTML size: {len(html_body)} chars (limit 20000)")

        pool_desc = client.describe_user_pool(UserPoolId=pool_id)['UserPool']

        # Lambda triggers per pool
        lambda_triggers = {
            'eu-south-1_0oK9agPYd': {'PostConfirmation': 'arn:aws:lambda:eu-south-1:881962383770:function:dev-cognito-post-confirmation'},
            'eu-south-1_1uXj751D4': {'PostConfirmation': 'arn:aws:lambda:eu-south-1:881962383770:function:dev-be-cognito-post-confirmation'},
            'eu-south-1_iCBtUlJO6': {'PostConfirmation': 'arn:aws:lambda:eu-south-1:881962383770:function:prod-cognito-post-confirmation'},
        }

        update_args = {
            'UserPoolId': pool_id,
            'AutoVerifiedAttributes': ['email'],
            'LambdaConfig': lambda_triggers.get(pool_id, {}),
            'EmailConfiguration': {
                'EmailSendingAccount': 'DEVELOPER',
                'SourceArn': 'arn:aws:ses:eu-south-1:881962383770:identity/girolavoro.it',
                'From': 'noreply@girolavoro.it',
            },
            'VerificationMessageTemplate': {
                'DefaultEmailOption': 'CONFIRM_WITH_CODE',
                'EmailMessage': html_body,
                'EmailSubject': "Il tuo codice di verifica girolavoro: {####}"
            }
        }
        
        # keep policies
        if 'Policies' in pool_desc:
            update_args['Policies'] = pool_desc['Policies']
            
        print(f"[{pool_id}] Aggiorno template email...")
        client.update_user_pool(**update_args)
        print(f"[{pool_id}] -> OK!")
        
    except Exception as e:
        print(f"[{pool_id}] -> ERRORE: {e}")

update_pool('eu-south-1_0oK9agPYd') # DEV
update_pool('eu-south-1_1uXj751D4') # DEV-BE
update_pool('eu-south-1_iCBtUlJO6') # PROD