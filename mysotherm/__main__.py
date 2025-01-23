#!/bin/env python3
from argparse import ArgumentParser
from datetime import datetime
import base64
import json
import logging
import os
from pprint import pprint
from urllib.parse import urlparse, urlunparse, quote

import pytz
import requests

from .util import slurpy
from . import mysa_stuff
from .mysa_stuff import BASE_URL
from .aws import boto3, botocore, Cognito


logging.basicConfig(format='[%(levelname)s:%(name)s] %(asctime)s - %(message)s',
    level=os.environ.get('LOGLEVEL', 'INFO').strip().upper())
logger = logging.getLogger(__name__)

p = ArgumentParser()
p.add_argument('-u', '--user', help='Mysa username', required=True)
p.add_argument('-p', '--password', help='Mysa password', required=True)
p.add_argument('-d', '--device', type=lambda s: s.replace(':','').lower(), help='Specific device (MAC address)')
p.add_argument('-W', '--no-watch', action='store_true', help="Just print device status, don't watch for realtime MQTT messages")
args = p.parse_args()

# Authenticate with pycognito
bsess = boto3.session.Session(region_name=mysa_stuff.REGION)
u = Cognito(
    user_pool_id=mysa_stuff.USER_POOL_ID,
    client_id=mysa_stuff.CLIENT_ID,
    username=args.user,
    session=bsess,
    pool_jwk=mysa_stuff.JWKS)
u.authenticate(password=args.password)

assert u.token_type == 'Bearer'
sess = requests.Session()
sess.headers.update(
    # It's a JWT, a bearer token, which means we *should* prefix it with "Bearer" in the
    # authorization header, but Mysa servers don't seem to accept it with the
    # "Bearer" prefix (although they seemingly used to: https://github.com/drinkwater99/MySa/blob/master/Program.cs#L35)
    authorization=u.id_token,
    **mysa_stuff.CLIENT_HEADERS
)

# Fetch a bunch of status info
user = sess.get(f'{BASE_URL}/users').json(object_hook=slurpy).User
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
    if args.device not in (None, did):
        continue
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
                        v = f'{vd.v*1.0:.2} A (UNDOCUMENTED FOR THIS DEVICE, MAY BE WRONG)'
                else:
                    v = f'{vd.v*1.0:.2} A (HIGHEST CURRENT SEEN)'
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

if args.no_watch:
    p.exit(0)

# Get AWS credentials with cognito-identity
cred = u.get_credentials(identity_pool_id="us-east-1:ebd95d52-9995-45da-b059-56b865a18379")

# Now we need to use these credentials to do a "SigV4 presigning" of the target URL that
# will be used for the HTTP->websockets connection: https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt
# Mysa is doing SigV4 in an odd (and potentially insecure) way, see comments in this function.
signed_mqtt_url = mysa_stuff.sigv4_sign_mqtt_url(cred)

mqtt_urlp = urlparse(mysa_stuff.MQTT_WS_URL)

# Let us touch the horrid boto3/AWS interfaces no more.

from websockets.sync.client import connect
from uuid import uuid1
from time import sleep
import mqttpacket.v311 as mqttpacket

with connect(
    urlparse(signed_mqtt_url)._replace(scheme='wss').geturl(),
    # We get 426 errors without the Sec-WebSocket-Protocol header:
    subprotocols=('mqtt',),
    # Seemingly not necessary for the server, but Mysa official client adds all this:
    origin=mqtt_urlp._replace(path='').geturl(),
    additional_headers={'accept-encoding': 'gzip'},
    user_agent_header=sess.headers['user-agent'],
) as ws:
    ws.send(mqttpacket.connect(str(uuid1()), 3600))
    l = mqttpacket.parse_one(ws.recv())
    pprint(l)

    for did in ((args.device,) if args.device else devices):
        ws.send(mqttpacket.subscribe(10, [
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/out', 0x01),
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/in', 0x01)
            ]))
        l = mqttpacket.parse_one(ws.recv())
        pprint(l)

    for wspkt in ws:
        msg = mqttpacket.parse_one(wspkt)
        if isinstance(msg, mqttpacket.PublishPacket):
            did, direction = msg.topic.split('/')[-2:]
            direction = '====>' if direction == 'in' else '<===='
            mac = ':'.join(did[n:n+2].upper() for n in range(0, len(did), 2))
            print(f'QOS={msg.qos} Retain={msg.retain} Dup={msg.dup} {direction} {devices[did].Name} (model {devices[did].Model!r}, mac {mac}, firmware {firmware[did].InstalledVersion}):')
            pprint(json.loads(msg.payload))
        else:
            pprint(msg)
