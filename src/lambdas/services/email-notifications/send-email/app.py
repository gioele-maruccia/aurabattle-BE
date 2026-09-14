"""
Generic SES Email Sender Lambda

Uses SendRawEmail with MIME multipart/related so that inline images are
delivered as CID attachments — guaranteed to render in all email clients
(Gmail, Outlook, Libero, Apple Mail, etc.) without requiring the client
to fetch any external URL.

Input event:
{
    "to": "recipient@example.com",
    "subject": "Your subject",
    "html_body": "<html>...</html>",
    "text_body": "Plain text fallback (optional)"
}

Environment variables:
    SES_FROM_ADDRESS  – verified sender address, e.g. noreply@girolavoro.it
    SES_REGION        – AWS region where SES is configured (default: eu-south-1)
"""

import json
import os
import re
import logging
import boto3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SES_FROM_ADDRESS = os.environ["SES_FROM_ADDRESS"]
SES_REGION = os.environ.get("SES_REGION", "eu-south-1")

ses = boto3.client("ses", region_name=SES_REGION)

# Images live in ./images/ inside the Lambda package (bundled at deploy time)
_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
_CID_IMAGES = {
    "girolavoro-logo": "blu.png",
    "fb-icon":      "fb_logo.png",
    "ig-icon":      "Instagram_logo.png",
}


def _build_mime(source: str, to_address: str, subject: str,
                html_body: str, text_body: str) -> MIMEMultipart:
    """Build a MIME multipart/related message with CID-embedded images."""
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = subject
    msg_root["From"] = source
    msg_root["To"] = to_address

    # multipart/alternative holds the text + html parts
    msg_alt = MIMEMultipart("alternative")
    msg_root.attach(msg_alt)
    if text_body:
        msg_alt.attach(MIMEText(text_body, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

    # Attach each image with a Content-ID so the HTML can reference it via cid:
    # NOTE: do NOT include filename in Content-Disposition — that causes
    # webmail clients (Libero, Outlook Web) to render them as attachments.
    for cid, filename in _CID_IMAGES.items():
        img_path = os.path.join(_IMAGES_DIR, filename)
        if os.path.exists(img_path):
            with open(img_path, "rb") as fp:
                msg_img = MIMEImage(fp.read())
            msg_img.add_header("Content-ID", f"<{cid}>")
            msg_img.add_header("Content-Disposition", "inline")
            msg_root.attach(msg_img)
        else:
            logger.warning(f"CID image not found at {img_path} — skipping")

    return msg_root


def handler(event, context):
    to_address = event.get("to")
    subject    = event.get("subject")
    html_body  = event.get("html_body")
    text_body  = event.get("text_body") or _strip_html(html_body or "")

    if not to_address or not subject or not html_body:
        logger.error(f"Missing required fields. event={json.dumps(event)}")
        return {"success": False, "error": "Missing to/subject/html_body"}

    try:
        msg = _build_mime(SES_FROM_ADDRESS, to_address, subject, html_body, text_body)
        response = ses.send_raw_email(
            Source=SES_FROM_ADDRESS,
            Destinations=[to_address],
            RawMessage={"Data": msg.as_string()},
        )
        message_id = response["MessageId"]
        logger.info(f"Email sent to {to_address} — MessageId={message_id}")
        return {"success": True, "message_id": message_id}

    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg  = exc.response["Error"]["Message"]
        logger.error(f"SES error sending to {to_address}: [{error_code}] {error_msg}")
        return {"success": False, "error": f"{error_code}: {error_msg}"}


def _strip_html(html: str) -> str:
    """Minimal HTML tag stripping for plain-text fallback."""
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()
