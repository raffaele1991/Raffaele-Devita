"""
Secret Verifier Module.

Verifica se i secret trovati nei file JavaScript sono effettivamente attivi
tramite chiamate API read-only. Se un secret risulta inattivo, viene scartato
per ridurre i falsi positivi.

Risultati:
    True  = secret verificato come ATTIVO
    False = secret verificato come INATTIVO
    None  = verifica non possibile (secret comunque segnalato)
"""

import datetime
import hashlib
import hmac
import logging
import re

import requests

logger = logging.getLogger("bugbounty_scanner")

VERIFY_TIMEOUT = 10


def verify_secret(secret_name, match_value, js_content=None):
    """
    Verifica se un secret è attivo.

    Args:
        secret_name: Tipo di secret (es. "GitHub Token")
        match_value: Il valore trovato dal pattern
        js_content: Contenuto completo del file JS (per cercare coppie di chiavi)

    Returns:
        True  = secret attivo
        False = secret inattivo
        None  = non verificabile
    """
    verifiers = {
        "GitHub Token": _verify_github_token,
        "Slack Token": _verify_slack_token,
        "Slack Webhook": _verify_slack_webhook,
        "Stripe Secret Key": _verify_stripe_secret,
        "SendGrid API Key": _verify_sendgrid,
        "Mailgun API Key": _verify_mailgun,
        "AWS Access Key": _verify_aws,
        "Twilio Account SID": _verify_twilio,
        "Google API Key": _verify_google_api,
    }

    verifier = verifiers.get(secret_name)
    if verifier is None:
        return None

    try:
        result = verifier(match_value, js_content)
        if result is True:
            logger.info(f"  [Verifier] {secret_name} ATTIVO")
        elif result is False:
            logger.info(f"  [Verifier] {secret_name} INATTIVO - scartato")
        return result
    except Exception as e:
        logger.debug(f"  [Verifier] Errore verifica {secret_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Verificatori per singolo token
# ---------------------------------------------------------------------------

def _verify_github_token(token, js_content=None):
    """GET https://api.github.com/user con il token."""
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "User-Agent": "BB-Scanner"},
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        return None
    except requests.RequestException:
        return None


def _verify_slack_token(token, js_content=None):
    """POST https://slack.com/api/auth.test con il token."""
    try:
        resp = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=VERIFY_TIMEOUT,
        )
        data = resp.json()
        return data.get("ok", False)
    except requests.RequestException:
        return None


def _verify_slack_webhook(url, js_content=None):
    """POST al webhook con payload vuoto: 400=esiste, 404=non esiste."""
    try:
        resp = requests.post(
            url,
            json={"text": ""},
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 404:
            return False
        if resp.status_code in (200, 400):
            return True
        return None
    except requests.RequestException:
        return None


def _verify_stripe_secret(key, js_content=None):
    """GET https://api.stripe.com/v1/balance con la chiave."""
    try:
        resp = requests.get(
            "https://api.stripe.com/v1/balance",
            auth=(key, ""),
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 401:
            return False
        return None
    except requests.RequestException:
        return None


def _verify_sendgrid(key, js_content=None):
    """GET https://api.sendgrid.com/v3/scopes con la chiave."""
    try:
        resp = requests.get(
            "https://api.sendgrid.com/v3/scopes",
            headers={"Authorization": f"Bearer {key}"},
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        return None
    except requests.RequestException:
        return None


def _verify_mailgun(key, js_content=None):
    """GET https://api.mailgun.net/v3/domains con la chiave."""
    try:
        resp = requests.get(
            "https://api.mailgun.net/v3/domains",
            auth=("api", key),
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        return None
    except requests.RequestException:
        return None


def _verify_google_api(key, js_content=None):
    """Testa Google API Key con Maps Geocoding."""
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": "test", "key": key},
            timeout=VERIFY_TIMEOUT,
        )
        data = resp.json()
        if data.get("status") in ("OK", "ZERO_RESULTS"):
            return True
        if data.get("status") == "REQUEST_DENIED":
            return False
        return None
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Verificatori che richiedono coppie di chiavi (cercate nello stesso file JS)
# ---------------------------------------------------------------------------

def _verify_aws(access_key, js_content=None):
    """
    Verifica AWS Access Key. Cerca il Secret Key nello stesso file JS
    e usa STS GetCallerIdentity per verificare la coppia.
    """
    if not js_content:
        return None

    secret_pattern = (
        r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY|secretAccessKey"
        r"|aws_secret|SecretAccessKey)\s*[:=]\s*['\"]([A-Za-z0-9/+=]{40})['\"]"
    )
    secret_match = re.search(secret_pattern, js_content)
    if not secret_match:
        return None

    secret_key = secret_match.group(1)

    # Prova con boto3 se disponibile
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = boto3.client(
            "sts",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        client.get_caller_identity()
        return True
    except ImportError:
        return _verify_aws_raw(access_key, secret_key)
    except Exception:
        return False


def _verify_aws_raw(access_key, secret_key):
    """Verifica AWS con richiesta HTTP firmata SigV4 a STS (senza boto3)."""
    region = "us-east-1"
    service = "sts"
    host = "sts.amazonaws.com"
    endpoint = f"https://{host}"

    now = datetime.datetime.utcnow()
    datestamp = now.strftime("%Y%m%d")
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")

    canonical_querystring = "Action=GetCallerIdentity&Version=2011-06-15"
    canonical_headers = f"host:{host}\nx-amz-date:{amzdate}\n"
    signed_headers = "host;x-amz-date"
    payload_hash = hashlib.sha256(b"").hexdigest()

    canonical_request = (
        f"GET\n/\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amzdate}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    def _sign(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(
            _sign(
                _sign(f"AWS4{secret_key}".encode(), datestamp),
                region,
            ),
            service,
        ),
        "aws4_request",
    )

    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"{algorithm} Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    try:
        resp = requests.get(
            f"{endpoint}?{canonical_querystring}",
            headers={
                "x-amz-date": amzdate,
                "Authorization": authorization,
                "Host": host,
            },
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        return None
    except requests.RequestException:
        return None


def _verify_twilio(account_sid, js_content=None):
    """Verifica Twilio Account SID cercando l'Auth Token nello stesso file."""
    if not js_content:
        return None

    token_pattern = (
        r"(?:auth_token|authToken|TWILIO_AUTH_TOKEN)"
        r"\s*[:=]\s*['\"]([a-f0-9]{32})['\"]"
    )
    token_match = re.search(token_pattern, js_content)
    if not token_match:
        return None

    auth_token = token_match.group(1)

    try:
        resp = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
            auth=(account_sid, auth_token),
            timeout=VERIFY_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        return None
    except requests.RequestException:
        return None
