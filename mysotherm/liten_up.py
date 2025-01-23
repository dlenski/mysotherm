#!/usr/bin/env
from argparse import ArgumentParser
import json
import logging
import os
from sys import stderr
from time import time, sleep
from uuid import uuid1
from urllib.parse import urlparse

logging.basicConfig(format='[%(levelname)s:%(name)s] %(asctime)s - %(message)s',
    level=os.environ.get('LOGLEVEL', 'INFO').strip().upper())
logger = logging.getLogger(__name__)

from .util import slurpy
from . import mysa_stuff
from .aws import boto3, botocore, Cognito
from .mysa_stuff import BASE_URL

from websockets.sync.client import connect
import mqttpacket.v311 as mqttpacket
import requests

p = ArgumentParser(description=
    '''This tool makes your Mysa Lite thermostat (model BB-V2-0-L) look like
    a Mysa Baseboard V1 thermostat (model BB-V1-1) to the official Mysa apps.

    This enables zone control, the usage graph, and the humidity sensor in the
    app.

    The Mysa Lite doesn't have a current sensor, and it doesn't report any
    estimated energy usage to the servers. TODO: Figure out how to report
    this to the server in a form it will accept, by estimating from the
    relay on/off signals.''')
p.add_argument('-u', '--user', help='Mysa username', required=True)
p.add_argument('-p', '--password', help='Mysa password', required=True)
p.add_argument('-d', '--device', action='append', type=lambda s: s.replace(':','').lower(), help='Specific device (MAC address)')
p.add_argument('-C', '--current', type=float, help="Estimated max current level (in Amperes). Mysa V2 Lite devices don't have current sensors.")
p.add_argument('-R', '--reset', action='store_true', help='Just reset faked Mysa Lite devices, and exit')
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
    authorization=u.id_token,
    **mysa_stuff.CLIENT_HEADERS
)

# This endpoint has the "real" device models, even after faking them in /devices
r = sess.get(f'{BASE_URL}/users')
r.raise_for_status()
user = r.json(object_hook=slurpy).User
real_models = {k: v.deviceType for k, v in user.DevicesPaired.State.BB.items()}

# Find applicable device(s)
if args.device:
    if args.device not in real_models:
        p.error(f'Mysa thermostat with ID (MAC address) of {args.device} not found in your account.')
    elif (m := real_models[args.device]) != 'BB-V2-0-L':
        p.error(f'Your Mysa thermostat {args.device} is model {m}, not BB-V2-0-L (Mysa V2 Lite). This trick is not applicable to it.')
    devices = (args.device,)
else:
    devices = [k for k, m in real_models.items() if m == 'BB-V2-0-L']
    if not devices:
        p.error(f'No Mysa thermostats with model BB-V2-0-L (Mysa V2 Lite) found in your account.')
    else:
        print(f'Found {len(devices)} with model BB-V2-0-L (Mysa V2 Lite) in your account.')

if args.reset:
    for did in devices:
        r = sess.post(f'{BASE_URL}/devices/{did}', json={'Model': 'BB-V2-0-L'})
        r.raise_for_status()
        print(f'Restored Mysa thermostat {args.device} to model BB-V2-0-L')
    p.exit(0)

# Check firmware versions
r = sess.get(f'{BASE_URL}/devices/firmware')
r.raise_for_status()
firmware = {k: v.InstalledVersion for k, v in r.json(object_hook=slurpy).Firmware.items()}
for did in devices:
    if (v := firmware.get(did)) is None:
        print(f'WARNING: Your Mysa thermostat {args.device} has an unknown firmware version. This might not work.\n'
               '  Please report success or failure at https://github.com/dlenski/mysotherm/issues or via email', file=stderr)
    elif not (3, 16, 2, 3) <= tuple(int(x) for x in v.split('.')) <= (3, 16, 2, 3):
        print(f'WARNING: Your Mysa thermostat {args.device} is on firmware version {v}. This has only been tested with v3.16.2.3'
               '  Please report success or failure at https://github.com/dlenski/mysotherm/issues or via email', file=stderr)

# Connect to MQTT-over-WebSockets endpoint
cred = u.get_credentials(identity_pool_id="us-east-1:ebd95d52-9995-45da-b059-56b865a18379")
signed_mqtt_url = mysa_stuff.sigv4_sign_mqtt_url(cred)
urlp = urlparse(signed_mqtt_url)
cid = str(uuid1)
with connect(
    urlp._replace(scheme='wss').geturl(),
    subprotocols=('mqtt',),
    # Seemingly not necessary for the server, but Mysa official client adds all this:
    origin=urlp._replace(path='', params='', query='', fragment='').geturl(),
    additional_headers={'accept-encoding': 'gzip'},
    user_agent_header=sess.headers['user-agent'],
) as ws:
    ws.send(mqttpacket.connect(str(uuid1()), 60))
    timeout = time() + 60
    pkt = mqttpacket.parse_one(ws.recv())
    assert isinstance(pkt, mqttpacket.ConnackPacket)

    # Subscribe to feeds for these devices
    for ii, did in enumerate(devices, 1):
        ws.send(mqttpacket.subscribe(ii, [
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/out', 0x01),
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/in', 0x01)
            ]))
        timeout = time() + 60
        pkt = mqttpacket.parse_one(ws.recv())
        assert isinstance(pkt, mqttpacket.SubackPacket) and pkt.packet_id == ii

    try:
        # Do the "magic upgrades"
        for did in devices:
            r = sess.post(f'{BASE_URL}/devices/{did}', json=
                {'Model': 'BB-V1-1', 'MaxCurrent': args.current})
            r.raise_for_status()

        # Await messages and translate as needed
        while True:
            try:
                pkt = mqttpacket.parse_one(ws.recv(timeout - time()))
                logging.debug(f'Received packet: {pkt}')
            except TimeoutError:
                pkt = None

            if isinstance(pkt, mqttpacket.PublishPacket):
                did, direction = pkt.topic.split('/')[-2:]
                payload = json.loads(pkt.payload, object_hook=slurpy)
                if direction == 'in' and payload.get('msg') == 44:
                    # Setpoint message for BB-V2-0 device (we need to change $TYPE from 1 to 5):
                    #
                    # {"Timestamp": $UNIXTIME,
                    #  "body": {"cmd": [{"sp": 17, "tm": -1}], "type": $TYPE, "ver": 1},
                    #  "dest": {"ref": "$DID", "type": 1},
                    #  "id": $UNIXTIMEMS,
                    #  "msg": 44,
                    #  "resp": 2,
                    #  "src": {"ref": "$USER_UUID", "type": 100},
                    #  "time": $UNIXTIME,
                    #  "ver": "1.0"}

                    assert payload.ver == "1.0"
                    assert payload.resp == 2
                    assert payload.dest == {'ref': did, 'type': 1}
                    body = payload.body
                    assert body.ver == 1
                    if body.type == 1:   # what the app sends for model BB-V1-1
                        body.type = 5    # ... what the model BB-V2-0-L actually wants
                        payload.id = int(time() * 1000)
                        payload.time = payload.timestamp = payload.id // 1000
                        opkt = mqttpacket.publish(pkt.topic, pkt.dup, pkt.qos, pkt.retain, packet_id=pkt.packetid ^ 0x8000,
                            payload=json.dumps(payload).encode())
                        logging.debug(f"Translated command packet for BB-V2-0 into BB-V2-0-L: {mqttpacket.parse(opkt)[1][0]}")

                        ws.send(opkt)
                        timeout = time() + 60
                    elif body.type == 5:
                        pass             # don't re-echo our own message

                if pkt.qos > 0:
                    ws.send(p := mqttpacket.puback(pkt.packetid))
                    logging.debug(f"Sent PUBACK packet for packet_id={pkt.packetid}")
                    timeout = time() + 60

            if timeout - time() < 5:
                ws.send(mqttpacket.pingreq())
                logging.debug(f"Sent PINGREQ keepalive packet")
                timeout = time() + 60

    except KeyboardInterrupt:
        print("Got interrupt (Ctrl-C)...")

    finally:
        print(f'Restoring Mysa V2 Lite thermostats to normal state...')
        for did in devices:
            r = sess.post(f'{BASE_URL}/devices/{did}', json={'Model': 'BB-V2-0-L'})
            r.raise_for_status
            print(f'Restored Mysa thermostat {did} to model BB-V2-0-L')
