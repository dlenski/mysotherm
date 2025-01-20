from .aws import botocore

REGION = 'us-east-1'
"""Region for Mysa AWS infrastructure"""

JWKS = {"keys":[{"alg":"RS256","e":"AQAB","kid":"udQ2TtD4g3Jc3dORobozGYu/T3qqcCtJonq0dwcrF8g=","kty":"RSA","n":"pwNwcNWr0CWijS_RlmooyzRq5Ud5GBDXKiTtS_4TV9MkXmxctKwiLFa_wnWsPw2B_RyQ6aY06de1qzylabuGcDQBpWFjmSWBoMiAFa2Facbhr4RnElLrs5MZTI3KZPVQlQaL0vvOERWC-3qe3HIG3EeaPyciSXS4aB2ldZCdLd2vtVJNwlzroqKiptXay9AeyQwiF6Tk2CXq4XZ3bcC5sFl53XjofoXXyZCrkBDjHBppE9Rhm0aw7u3DSozPbkiAEK-x92xQZ-Ymrl1eTLL4J08KiBdog2gVWYJqM9DdJ1T0rTBNXxNKgpnP9M83KnN8ViRgayBfLlyLpOOFaFK5lw","use":"sig"},{"alg":"RS256","e":"AQAB","kid":"f5vP7g+ehnb4PP+90i1WVsnUNfccQZVReBmaRvrHga0=","kty":"RSA","n":"nKGdPVq3wzz8Cy8tLwZ7OP44avSrNf-fcvqLV-lRG-9ziZavn4L7an2KZy_MDmdxBSekVDUoERAJNhNRlLFVRt_ialnUwkuZw0hkzeVyRT50-jE1bieF4I_zjOm7t_QhJTMoLG2KuDZcaGZa5RpDXZJGwPGKxcFjpH_VwgxFDwlTYPc2BjofuW8OwKNdm1CMNstG94pxGZoRuak_wd3Sg20DXH1c43kmHCiy4Ish-3oVHYMhVNv-pra02HXr-fJv8Rd7E0nVfw_Iki8MfWE6C5NunMCx74rigHbMMKZrzQtnB4EdxlcqZWjkC_5Qd1AhM6-gYchXMCKq18COrPPR1w","use":"sig"}]}
"""
These are the "well-known JWKs" for Mysa's Cognito IDP user pool.
Cached from https://cognito-idp.us-east-1.amazonaws.com/us-east-1_GUFWfhI7g/.well-known/jwks.json so
that we don't need to re-fetch them.
"""

USER_POOL_ID = "us-east-1_GUFWfhI7g"
"""
Mysa's Cognito IDP user pool
(https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html)
"""

CLIENT_ID = "19efs8tgqe942atbqmot5m36t3"
"""Mysa's Cognito IDP client ID"""

IDENTITY_POOL_ID = "us-east-1:ebd95d52-9995-45da-b059-56b865a18379"
"""
Mysa's Cognito Identity pool ID
"An Amazon Cognito identity pool is a directory of federated identities that you can exchange for AWS credentials."
(https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-identity.html)
"""

MQTT_WS_URL = "https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt"
"""
"""

CLIENT_HEADERS = {
    'user-agent': 'okhttp/4.11.0',
    'accept': 'application/json',
    'accept-encoding': 'gzip',
}
"""Mysa Android app 3.62.4 sends these headers, although the server doesn't seem to care"""

BASE_URL = 'https://app-prod.mysa.cloud'
"""Base URL for Mysa's JSONful API"""


def sigv4_sign_mqtt_url(cred: botocore.credentials.Credentials):
    """
    Mysa is doing SigV4 in an odd (and potentially insecure) way!

    The gory details of the SigV4 algorithm are here: https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    ... and a fairly minimal Python example is here: https://gist.github.com/marcogrcr/6f0645b20847be4ef9cd6742427fc97b#file-sigv4_using_requests-py-L34-L51

    If you look very closely at the URLs from a capture of the Mysa app:

    1. The parameter order is strange:
        https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt
        ?X-Amz-Algorithm=AWS4-HMAC-SHA256
        &X-Amz-Credential=${AWS_ACCESS_KEY_ID}%2F${YYYYMMDD}%2Fus-east-1%2Fiotdevicegateway%2Faws4_request
        &X-Amz-Date=${YYYYMMDD}T${HHmmSS}Z
        &X-Amz-SignedHeaders=host
        &X-Amz-Signature=${SIGNATURE}                    <-- based on all examples, this should be the last parameter
        &X-Amz-Security-Token=${AWS_SESSION_TOKEN}       <-- this should have been included in the to-be-signed URL
    2. You can modify the exact bytes of 'X-Amz-Security-Token' (e.g. replacing '%2E' with '%2e') without
       breaking its functionality; this would not be the case if it were actually part of the to-be-signed URL.

    The docs (https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html#:~:text=you%20must%20include%20the%20X%2DAmz%2DSecurity%2DToken%20query%20parameter%20in%20the%20URL%20if%20using%20credentials%20sourced%20from%20the%20STS%20service.)
    say that if you are using credentials sourced from the STS service, the X-Amz-Security-Token query parameter
    must be included in the to-be-signed URL. (At least for S3.)

    But if we follow that, we get the wrong signature... results in 403 Forbidden errors.

    What I realized is that Mysa is actually doing the signature *without* the session token, and then adding
    the session token afterwards.
    """

    req = botocore.awsrequest.AWSRequest('GET', MQTT_WS_URL)
    botocore.auth.SigV4QueryAuth(
        credentials=cred.get_frozen_credentials()._replace(token=None), # Strip the session token before signing
        service_name='iotdevicegateway',
        region_name='us-east-1').add_auth(req)
    req.params['X-Amz-Security-Token'] = cred.token  # Plunk the session into the URL after signing
    return req.prepare().url
