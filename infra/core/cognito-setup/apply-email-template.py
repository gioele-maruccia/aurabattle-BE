"""
Applica il template email di verifica account su Cognito.
Usato dai deploy scripts (deploy-dev.ps1 / deploy-prod.ps1).

Usage:
    python apply-email-template.py <user_pool_id> <region> <lambda_arn>
"""
import sys
import re
import pathlib
import boto3

def main():
    if len(sys.argv) != 4:
        print("Usage: python apply-email-template.py <user_pool_id> <region> <lambda_arn>")
        sys.exit(1)

    user_pool_id = sys.argv[1]
    region       = sys.argv[2]
    lambda_arn   = sys.argv[3]

    template_path = pathlib.Path(__file__).parent / "email-verification-template.html"
    if not template_path.exists():
        print(f"[WARN] Template non trovato: {template_path}")
        print("[WARN] Uso la configurazione email di default Cognito")
        email_message = None
    else:
        raw = template_path.read_text(encoding="utf-8")
        # Collassa newline e spazi multipli in una sola riga
        email_message = re.sub(r'\s+', ' ', raw).strip()
        print(f"[OK] Template caricato: {len(email_message)} caratteri")

    client = boto3.client("cognito-idp", region_name=region)

    verification_template = {"DefaultEmailOption": "CONFIRM_WITH_CODE"}
    if email_message:
        verification_template["EmailSubject"] = "Il tuo codice di verifica beebusy"
        verification_template["EmailMessage"] = email_message

    response = client.update_user_pool(
        UserPoolId=user_pool_id,
        LambdaConfig={"PostConfirmation": lambda_arn},
        AutoVerifiedAttributes=["email"],
        VerificationMessageTemplate=verification_template,
    )

    status = response["ResponseMetadata"]["HTTPStatusCode"]
    if status == 200:
        print("[OK] Trigger PostConfirmation e template email configurati su Cognito")
    else:
        print(f"[ERROR] HTTP {status}")
        sys.exit(1)

if __name__ == "__main__":
    main()
