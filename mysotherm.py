#!/bin/env python3
from argparse import ArgumentParser
from datetime import datetime
import base64
import logging
import os
from pprint import pprint
from urllib.parse import urlparse, urlunparse, quote

# boto3 is stupid AF and by default it wastes 1 second trying to connect to EC2 metadata
# every single time you run it, unless you set these environment variables
# https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html
os.environ['AWS_EC2_METADATA_DISABLED'] = 'true'        # <-- only works if boto3 hasn't yet been imported 🤬
#os.environ['AWS_METADATA_SERVICE_NUM_ATTEMPTS'] = '0'  # <-- works even after boto3 imported
#os.environ['AWS_METADATA_SERVICE_TIMEOUT'] = '0'       # <-- redundant, unnecessary

import boto3, botocore
import pycognito
import pytz
import requests

#os.environ['AWS_EC2_METADATA_DISABLED'] = 'true'
logging.basicConfig(format='[%(levelname)s:%(name)s] %(asctime)s - %(message)s',
    level=os.environ.get('LOGLEVEL', 'INFO').strip().upper())
logging.getLogger('urllib3').setLevel(logging.DEBUG)
logging.getLogger('websockets.client').setLevel(logging.DEBUG)


p = ArgumentParser()
p.add_argument('-u', '--user', help='Mysa username')
p.add_argument('-p', '--password', help='Mysa password')
args = p.parse_args()

# Quacks like a dict and an object (https://github.com/dlenski/wtf/blob/master/wtf.py#L10C1-L19C1),
# and has the option to add aliases.
class slurpy(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(*e.args)

# Pycognito needs to fetch https://cognito-idp.us-east-1.amazonaws.com/us-east-1_GUFWfhI7g/.well-known/jwks.json,
# unless we cache it in this environment variable.
os.environ['COGNITO_JWKS'] = '{"keys":[{"alg":"RS256","e":"AQAB","kid":"udQ2TtD4g3Jc3dORobozGYu/T3qqcCtJonq0dwcrF8g=","kty":"RSA","n":"pwNwcNWr0CWijS_RlmooyzRq5Ud5GBDXKiTtS_4TV9MkXmxctKwiLFa_wnWsPw2B_RyQ6aY06de1qzylabuGcDQBpWFjmSWBoMiAFa2Facbhr4RnElLrs5MZTI3KZPVQlQaL0vvOERWC-3qe3HIG3EeaPyciSXS4aB2ldZCdLd2vtVJNwlzroqKiptXay9AeyQwiF6Tk2CXq4XZ3bcC5sFl53XjofoXXyZCrkBDjHBppE9Rhm0aw7u3DSozPbkiAEK-x92xQZ-Ymrl1eTLL4J08KiBdog2gVWYJqM9DdJ1T0rTBNXxNKgpnP9M83KnN8ViRgayBfLlyLpOOFaFK5lw","use":"sig"},{"alg":"RS256","e":"AQAB","kid":"f5vP7g+ehnb4PP+90i1WVsnUNfccQZVReBmaRvrHga0=","kty":"RSA","n":"nKGdPVq3wzz8Cy8tLwZ7OP44avSrNf-fcvqLV-lRG-9ziZavn4L7an2KZy_MDmdxBSekVDUoERAJNhNRlLFVRt_ialnUwkuZw0hkzeVyRT50-jE1bieF4I_zjOm7t_QhJTMoLG2KuDZcaGZa5RpDXZJGwPGKxcFjpH_VwgxFDwlTYPc2BjofuW8OwKNdm1CMNstG94pxGZoRuak_wd3Sg20DXH1c43kmHCiy4Ish-3oVHYMhVNv-pra02HXr-fJv8Rd7E0nVfw_Iki8MfWE6C5NunMCx74rigHbMMKZrzQtnB4EdxlcqZWjkC_5Qd1AhM6-gYchXMCKq18COrPPR1w","use":"sig"}]}'

# pycognito neatly wraps PART OF what we need here
bsess = boto3.session.Session(region_name='us-east-1')
#print(type(c))
u = pycognito.Cognito(
    user_pool_id='us-east-1_GUFWfhI7g',
    client_id='19efs8tgqe942atbqmot5m36t3',
    username=args.user,
    session=bsess)
u.authenticate(password=args.password)
#pprint(vars(u))

assert u.token_type == 'Bearer'
sess = requests.Session()
sess.headers.update({
    # It's a JWT, a bearer token, which means we *should* prefix it with "Bearer" in the
    # authorization header, but Mysa servers don't seem to accept it with the
    # "Bearer" prefix (although they seemingly used to: https://github.com/drinkwater99/MySa/blob/master/Program.cs#L35)
    'authorization': u.id_token,

    # Mysa Android app 3.62.4 sends these headers, although the server doesn't seem to care
    'user-agent': 'okhttp/4.11.0',
    'accept': 'application/json',
    'accept-encoding': 'gzip',
})

BASE_URL='https://app-prod.mysa.cloud'

devices = sess.get(f'{BASE_URL}/devices').json(object_hook=slurpy).DevicesObj
states = sess.get(f'{BASE_URL}/devices/state').json(object_hook=slurpy).DeviceStatesObj
firmware = sess.get(f'{BASE_URL}/devices/firmware').json(object_hook=slurpy).Firmware
# Have also seen:
#   GET /devices/capabalities (empty for me)
#   GET /devices/drstate (empty for me)
#   GET /homes, /homes/{home_uuid}, /users, /users/{user_uuid}, /schedules, etc (-> JSON)
#   PATCH /users/{user_uuid} (-> set app info)
#   POST /energy/setpoints/device/{device_id} (-> mystifyingly, this is NOT setting the device setpoint, only reading it?? payload={"PhoneTimezone": "America/Vancouver", "Scope": "Day","Timestamp": 1736700658}

for did, d in devices.items():
    assert did == d.Id
    # Device ID is its WiFi MAC addresses. To get its Bluetooth MAC address, add 2 to the last byte
    mac = ':'.join(did[n:n+2].upper() for n in range(0, len(did), 2))
    print(f'{d.Name} (model {d.Model!r}, mac {mac}, firmware {firmware[did].InstalledVersion}):')
    tz = pytz.timezone(d.TimeZone)
    if (s := states.get(did)) is None:
        print('  No state found!')
    else:
        assert did == s.pop('Device')
        mints, maxts = 1<<32, 0
        width = max(len(k) for k in s)
        for k, vd in sorted(s.items()):
            if not isinstance(vd, dict):
                vd = slurpy(v=vd, t=None)  # sometimes {"v": value, "t": timestamp}, sometimes bare value?
            else:
                if vd.t > 1000<<30:
                    vd.t /= 1000   # sometimes ms, sometimes seconds!? that's insane
                if vd.t > maxts:
                    maxts = vd.t
                elif vd.t < mints:
                    mints = vd.t

            if vd.v == -1:
                vd.v = None  # missing/invalid values, I think

            if k in ('SensorTemp', 'CorrectedTemp', 'SetPoint', 'HeatSink'):
                if d.Format == 'fahrenheit':
                    v = f'{32+vd.v*9/5:.1f}°F'
                else:
                    v = f'{vd.v}°C'
            elif k == 'Timestamp':
                # I'm not sure what this timestamp is, exactly
                v = datetime.fromtimestamp(vd.v, tz=tz)
            elif k == 'Current':
                if d.Model == 'BB-V2-0-L':
                    # From an email from Mysa support:
                    # "the Mysa V2 LITE model you have does not have a current sensor, so if there is an open load issues, it will not display the H2 error."
                    if vd.v == 0:
                        v = 'None (DEVICE HAS NO CURRENT SENSOR)'
                    else:
                        v = f'{vd.v:.2} A (UNDOCUMENTED FOR THIS DEVICE, MAY BE WRONG)'
                else:
                    v = f'{vd.v:.2} A (HIGHEST CURRENT SEEN)'
            elif k == 'Duty':
                if d.Model == 'BB-V2-0-L' and vd.v in (0, 1):
                    v = f'{"On" if vd.v else "Off":4} (DEVICE HAS NO CURRENT SENSOR)'
                else:
                    v = f'{vd.v*100.0:.0f}% (OF HIGHEST CURRENT)'
            elif k == 'Brightness': v = f'{vd.v}%'
            elif k == 'Voltage':    v = f'{vd.v} V'
            elif k == 'Rssi':       v = vd.v and f'{vd.v} dBm'
            elif k == 'Lock':       v = bool(vd.v) if vd.v in (0, 1) else vd.v
            elif k == 'Humidity':
                v = f'{vd.v}%'
                if d.Model == 'BB-V2-0-L':
                    # The Mysa Lite does not advertise a humidity sensor, and the app does not *show* a humidity sensor,
                    # but the device reports a humidity reading which moves up and down when I hold a cup of steaming hot water
                    # under it. The sensor might be on-chip but uncalibrated and unexposed.
                    # https://guides.getmysa.com/help/mysa-for-electric-baseboard-heaters-v1-and-v2/t/cl3uk6csw1479029ejm93kn4q631
                    v += ' (UNDOCUMENTED FOR THIS DEVICE, MAY BE WRONG)'
            else:
                v = vd.v

            print(f'  {k+":":{width+1}} {v}')
        else:
            mints = datetime.fromtimestamp(mints, tz=tz)
            maxts = datetime.fromtimestamp(maxts, tz=tz)
            print(f'  Last updates between {mints} - {maxts}')


# Pycognito unfortuntaely doesn't help us to get the plain AWSCredentials
# object from 'cognito-identity'
ic = bsess.client('cognito-identity')
logins={u.id_claims['iss'].removeprefix('https://'): u.id_token}  # "cognito-idp.us-east-1.amazonaws.com/us-east-1_GUFWfhI7g"
r1 = slurpy(ic.get_id(IdentityPoolId="us-east-1:ebd95d52-9995-45da-b059-56b865a18379", Logins=logins))
assert r1.IdentityId == 'us-east-1:c04f27e0-59c8-c717-da9f-889f412f6623'
r2 = slurpy(ic.get_credentials_for_identity(IdentityId=r1.IdentityId, Logins=logins))
c = slurpy(r2.Credentials)
cred = botocore.credentials.ReadOnlyCredentials(c.AccessKeyId, c.SecretKey, c.SessionToken)
#pprint(r1)
#pprint(r2)

# Now we need to use these credentials to do a "SigV4 presigning" of the target URL that
# will be used for the HTTP->websockets connection: https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt
# The gory details of the algorithm are here: https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
# ... and a fairly minimal Python example is here: https://gist.github.com/marcogrcr/6f0645b20847be4ef9cd6742427fc97b#file-sigv4_using_requests-py-L34-L51
#
# But the most crucial detail is that Mysa is doing SigV4 in an odd (and potentially insecure) way!
#
# If you look very closely at the URLs from a capture of the Mysa app, the parameter order is strange:
#     https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt
#       ?X-Amz-Algorithm=AWS4-HMAC-SHA256
#       &X-Amz-Credential=${AWS_ACCESS_KEY_ID}%2F${YYYYMMDD}%2Fus-east-1%2Fiotdevicegateway%2Faws4_request
#       &X-Amz-Date=${YYYYMMDD}T${HHmmSS}Z
#       &X-Amz-SignedHeaders=host
#       &X-Amz-Signature=${SIGNATURE}                    <-- based on all example, this should be the last parameter
#       &X-Amz-Security-Token=${AWS_SESSION_TOKEN}       <-- this should have been included in the to-be-signed URL
#
# The docs (https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html#:~:text=you%20must%20include%20the%20X%2DAmz%2DSecurity%2DToken%20query%20parameter%20in%20the%20URL%20if%20using%20credentials%20sourced%20from%20the%20STS%20service.)
# say that if you are using credentials sourced from the STS service, the X-Amz-Security-Token query parameter
# must be included in the to-be-signed URL. (At least for S3.)
#
# But if we follow that, we get the wrong signature... results in 403 Forbidden errors.
#
# What I realized is that Mysa is actually doing the signature *without* the session token, and then adding
# the session token afterwards.

mqtt_url = 'https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt'
mqtt_urlp = urlparse(mqtt_url)
req = botocore.awsrequest.AWSRequest(
    method='GET',
    url=mqtt_url,
    data=None,
    headers={'Host': mqtt_urlp.hostname},
)
botocore.auth.SigV4QueryAuth(
    credentials=cred._replace(token=None), # Strip the session token before signing
    service_name='iotdevicegateway',
    region_name='us-east-1').add_auth(req)
req = req.prepare()
req.url += '&X-Amz-Security-Token=' + quote(cred.token)  # Plunk the session onto the URL after

# Let us touch the horrid boto3/AWS interfaces no more.

from websockets.sync.client import connect
from uuid import uuid1
from time import sleep
import mqttpacket.v311 as mqttpacket

with connect(
    urlparse(req.url)._replace(scheme='wss').geturl(),
    # We get 426 errors without the Sec-WebSocket-Protocol header:
    subprotocols=('mqtt',),
    # Seemingly not necessary for the server, but Mysa official client adds all this:
    origin=mqtt_urlp._replace(path='').geturl(),
    additional_headers=sess.headers,
    #user_agent_header=sess.headers['user-agent'],
) as ws:
    ws.send(mqttpacket.connect(str(uuid1())))
    sleep(1)
    ws.send(mqttpacket.subscribe(10, [
        mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/out', 0x01) for did in devices]
        ))

    for msg in ws:
        print(msg)
