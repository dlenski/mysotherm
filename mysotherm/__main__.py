#!/bin/env python3
from argparse import ArgumentParser
from datetime import datetime
from itertools import chain
from copy import deepcopy
import base64
import json
import logging
import os
import struct
from pprint import pprint
from urllib.parse import urlparse, urlunparse, quote
from time import time, sleep
from uuid import uuid1

import pytz
import requests
from websockets.sync.client import connect
import mqttpacket.v311 as mqttpacket

from .util import slurpy
from . import mysa_stuff
from .mysa_stuff import BASE_URL
from .aws import boto3, botocore, Cognito


logging.basicConfig(format='[%(levelname)s:%(name)s] %(asctime)s - %(message)s',
    level=os.environ.get('LOGLEVEL', 'INFO').strip().upper())
logger = logging.getLogger(__name__)

def main(args=None):
    p = ArgumentParser()
    p.add_argument('-u', '--user', help='Mysa username', required=True)
    p.add_argument('-p', '--password', help='Mysa password', required=True)
    p.add_argument('-d', '--device', action='append',
                   type=lambda s: s.replace(':','').lower(), help='Specific device (MAC address); may be repeated')
    p.add_argument_group('Debugging options')
    p.add_argument('-W', '--no-watch', action='store_true', help="Exit after printing status information, don't watch for realtime MQTT messages")
    p.add_argument('--dump-lots', action='store_true', help='Dump JSON from a whole bunch of endpoints.')
    p.add_argument('--dump-token', action='store_true', help='Dump access token and cURL command.')
    args = p.parse_args(args)

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

    if args.dump_token:
        print("Cognito ID token:")
        print("=================")
        print(u.id_token)
        print("Cognito ID claims:")
        print("==================")
        pprint(u.id_claims)
        print("cURL template:")
        print("==============")
        print(f"curl -H 'authorization: {u.id_token}' '{BASE_URL}'")

    # Fetch a bunch of status info
    user = sess.get(f'{BASE_URL}/users').json(object_hook=slurpy).User
    devices = sess.get(f'{BASE_URL}/devices').json(object_hook=slurpy).DevicesObj
    states = sess.get(f'{BASE_URL}/devices/state').json(object_hook=slurpy).DeviceStatesObj
    firmware = sess.get(f'{BASE_URL}/devices/firmware').json(object_hook=slurpy).Firmware
    # Have also seen:
    #   GET /devices/capabilities (empty for me)
    #   GET /devices/drstate (empty for me)
    #   GET /homes, /homes/{home_uuid}, /users, /users/{user_uuid}, /schedules, etc (-> JSON)
    #   PATCH /users/{user_uuid} (-> set app info)
    #   POST /energy/setpoints/device/{device_id} (-> this is NOT setting the device setpoint, only reading it. Payload is {"PhoneTimezone": "America/Vancouver", "Scope": "Day","Timestamp": 1736700658}
    #   POST /energy/device/{device_id} (-> reading the device energy usage and temp/humidity readings. Same payload.)
    #   GET /devices/state/{device_id}

    if args.dump_lots:
        print("GET /users | .json() | .User")
        print("============================")
        pprint(user)
        print("GET /devices | .json() | .DevicesObj")
        print("====================================")
        pprint(devices)
        print("GET /devices/state | .json() | .DeviceStatesObj")
        print("===============================================")
        pprint(states)
        print("GET /devices/firmware | .json() | .Firmware")
        print("===========================================")
        pprint(firmware)

    if args.device:
        if (missing := set(args.device) - set(devices)):
            p.error(f"Device ID(s) {', '.join(missing)} not found in your Mysa account.")
        devices = {did: devices[did] for did in args.device}

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
        return

    print("Connecting to MQTT endpoint to watch real-time messages...")

    # Get AWS credentials with cognito-identity
    cred = u.get_credentials(identity_pool_id="us-east-1:ebd95d52-9995-45da-b059-56b865a18379")

    # Now we need to use these credentials to do a "SigV4 presigning" of the target URL that
    # will be used for the HTTP->websockets connection: https://a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com/mqtt
    # Mysa is doing SigV4 in an odd (and potentially insecure) way, see comments in this function.
    signed_mqtt_url = mysa_stuff.sigv4_sign_mqtt_url(cred)

    mqtt_urlp = urlparse(mysa_stuff.MQTT_WS_URL)

    # Let us touch the horrid boto3/AWS interfaces no more.


    with connect(
        urlparse(signed_mqtt_url)._replace(scheme='wss').geturl(),
        # We get 426 errors without the Sec-WebSocket-Protocol header:
        subprotocols=('mqtt',),
        # Seemingly not necessary for the server, but Mysa official client adds all this:
        origin=mqtt_urlp._replace(path='').geturl(),
        additional_headers={'accept-encoding': 'gzip'},
        user_agent_header=sess.headers['user-agent'],
    ) as ws:
        ws.send(mqttpacket.connect(str(uuid1()), 60))
        assert isinstance(mqttpacket.parse_one(ws.recv()), mqttpacket.ConnackPacket)

        subs = list(chain.from_iterable((
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/out', 0x01),
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/in', 0x01),
            mqttpacket.SubscriptionSpec(f'/v1/dev/{did}/batch', 0x01),
        ) for did in devices))
        ws.send(mqttpacket.subscribe(1, subs))
        assert isinstance((l := mqttpacket.parse_one(ws.recv())), mqttpacket.SubackPacket)

        print("Connected to MQTT endpoint and subscribed to device in/out message...")

        timeout = time() + 60
        while True:
            now = time()
            try:
                msg = mqttpacket.parse_one(ws.recv(timeout - time()))
                logging.debug(f'Received packet: {msg}')
            except TimeoutError:
                pkt = None
                ws.send(mqttpacket.pingreq())
                logging.debug(f"Sent PINGREQ keepalive packet")
                timeout = now + 60
            else:
                if isinstance(msg, mqttpacket._packet.PingrespPacket):
                    pass
                elif isinstance(msg, mqttpacket.PublishPacket):
                    did, subtopic = msg.topic.split('/')[-2:]
                    if subtopic == 'in':
                        arrow = 'TO   ==>'
                    elif subtopic == 'out':
                        arrow = 'FROM <=='
                    elif subtopic == 'batch':
                        arrow = 'FROM <=='    # these are always FROM the device, right?
                    else:
                        arrow = f'?{subtopic}?'
                    mac = ':'.join(did[n:n+2].upper() for n in range(0, len(did), 2))
                    deets = ''.join(filter(None, [
                        msg.qos and f' QOS={msg.qos}',
                        msg.retain and ' +retain',
                        msg.dup and ' +dup',
                    ]))

                    understood = ts = orig_json = None

                    try:
                        j = json.loads(msg.payload, object_hook=slurpy)
                        orig_json = deepcopy(j)
                        if (mt := j.pop('MsgType', None)) is not None:
                            assert j.pop('Device') == did
                            ts = j.pop('Timestamp')
                            if mt == 11 and subtopic == 'in':
                                understood = f'App telling device to publish its status ({json.dumps(j)})'
                            elif mt == 6 and subtopic == 'in':
                                understood = f'App telling device to check its settings ({json.dumps(j)})'
                            elif mt == 4 and subtopic == 'out':
                                understood = f'Device log [{j.Level}] {j.Message}'
                            elif mt == 0 and subtopic == 'out':
                                assert j.pop('Stream') == 1
                                understood = f'Device (V1?) reporting its status: {json.dumps(j)}'
                            elif mt == 1 and subtopic == 'out':
                                understood = f'Unclear prev/next message from device: {json.dumps(j)}'
                        elif (mt := j.pop('msg')) is not None:
                            if mt == 40:
                                assert j.pop('ver') == '1.0'
                                assert j.pop('src') == {'ref': did, 'type': 1}
                                ts = j.pop('time')
                                body = j.pop('body')
                                understood = f'Device (V2?) reporting its status: {json.dumps(body)}'
                            elif mt == 44 and subtopic == 'in':
                                ts = j.pop('id') / 1000
                                assert j.pop('ver') == '1.0'
                                assert j.pop('dest') == {'ref': did, 'type': 1}
                                assert j.pop('resp') == 2
                                assert abs(j.pop('Timestamp') - int(ts)) <= 1   # Sometimes randomly off by 1 sec
                                assert j.pop('time') == int(ts)
                                assert 'timestamp' not in j or j.pop('timestamp') == int(ts)
                                src = j.pop('src')
                                if src == {'ref': user.Id, 'type': 100}:
                                    by = 'You'
                                elif src.type == 100:
                                    by = f'Other user {src.ref}'
                                else:
                                    by = json.dumps(src)
                                assert set(j.keys()) == {'body'}
                                body = j.body
                                assert body.pop('ver')
                                weird = ' (derpy stringified cmd)' if isinstance(body['cmd'], str) else ''
                                understood = f'{by} commanding device{weird}: {json.dumps(body)}'
                            elif mt == 44 and subtopic == 'out':
                                ts = j.pop('time')
                                assert j.pop('ver') == '1.0'
                                assert j.pop('src') == {'ref': did, 'type': 1}
                                assert abs(ts - j.pop('resp_id') / 1000) <= 5  # <=5 sec delay
                                id_ = j.pop('id')
                                assert set(j.keys()) == {'body'}
                                body = j.body
                                assert body.pop('success') == 1
                                understood = f'Device responding to app command: {json.dumps(body)} (id={id_})'
                            elif mt == 3 and subtopic == 'batch':
                                ts = j.pop('time')
                                assert j.pop('ver') == '1.0'
                                assert j.pop('src') == {'ref': did, 'type': 1}
                                id_ = j.pop('id')
                                body = j.pop('body')
                                assert not(j)
                                readings = base64.b64decode(body.pop('readings'))
                                assert not body
                                understood = parse_readings(readings)
                    except Exception:
                        ts = time()

                    if understood and ts:
                        understood = f'[{now - ts:.1f}s ago] ' + understood

                    if did in devices:
                        print(f'{arrow} {devices[did].Name}{deets} (model {devices[did].Model!r}, mac {mac}, firmware {firmware[did].InstalledVersion}):')
                    else:
                        print(f'{arrow} Unknown device {did} (topic {msg.topic})')

                    if understood:
                        print(f'  {understood}')
                    elif orig_json:
                        print(f'  {json.dumps(orig_json)}')
                    else:
                        print(f'  {msg.payload}')

                    if msg.qos > 0:
                        ws.send(mqttpacket.puback(msg.packetid))
                        timeout = time() + 60
                else:
                    pprint(msg)

def parse_readings(readings: bytes):
    if not readings.startswith(b'\xca\xa0'):
        return f'Unknown-format device readings of length 0x{len(readings):04x}:\n' + ''.join(f'  {ii:04x}  {readings[ii:ii+16].hex(" ", 8)}\n' for ii in range(0, len(readings), 16))
    offset = 0
    ver = readings[2]
    understood = f'Raw readings (v{ver}):\n'
    while offset < len(readings):
        assert readings[offset: offset+2] == b'\xca\xa0' # All should have same prefix
        assert readings[offset+2] == ver                # ... and same version
        offset += 3
        sts, sens, amb, setp, hum, dty, onish, offish, heatsink, flags = struct.unpack_from('<Lhhhbbhhhh', readings, offset)
        offset += 20
        sens /= 10; amb /= 10; setp /= 10; heatsink /= 10   # Unit = 0.1°C
        if ver == 3:   # BB-V2-0 / BB-V2-0-L
            tu = 'ms'                               # Unit [of onish/offish] = 1 ms
            always1, onoroff, voltage, current, always0, crc = struct.unpack_from('<bbhh3sB', readings, offset)
            offset += 10
            current *= 10                           # Unit = 10 mA
            variant = f'one?={always1}, on|off={onoroff}, voltage={voltage}V, cur={current}mA, zero?={always0.hex()}, crc?={crc:08b}'
        elif ver == 0:   # BB-V1-0
            onish *= 100; offish *= 100; tu = 'ms'  # Unit = 100 ms
            rssi, onoroff, crc = struct.unpack_from('<bbB', readings, offset)
            offset += 3
            rssi = -rssi                            # Unit = -1 dBm
            variant = f'rssi={rssi} dBm, on|off={onoroff}, crc(?)={crc:08b}'
        else:
            # Unknown versions
            # v4 = Air conditioners (offset += 20), v1 = Unknown (offset += 5)
            tu = '?'                                                           # We don't know the time unit
            if (end := readings.find(bytes((0xca, 0xa0, ver)), offset)) < 0:  # Hopefully no inadvertent matching bytes!!
                end = len(radings)
            variant = readings[offset:end].hex(' ', -4)
            offset = end
        understood += f'  {datetime.fromtimestamp(sts)}: sens={sens:.1f}°C, amb={amb:.1f}°C, setp={setp:.1f}°C, hum={hum}%, dty={dty}%, on?={onish}{tu}, off?={offish}{tu}, heatsink={heatsink:.1f}°C, flags?={flags:04x}, {variant}\n'
    return understood

if __name__ == '__main__':
    main()
