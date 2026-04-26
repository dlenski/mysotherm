from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from time import time
from functools import reduce
import struct

import botocore
import requests

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

MQTT_WS_HOST = "a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com"
"""
Hostname for Mysa MQTT-over-WebSockets endpoint
"""

MQTT_WS_URL = f"https://{MQTT_WS_HOST}/mqtt"
"""
Complete HTTPS URL to initiate Mysa MQTT-over-Websockets connection
"""

CLIENT_HEADERS = {
    'user-agent': 'okhttp/4.11.0',
    'accept': 'application/json',
    'accept-encoding': 'gzip',
}
"""Mysa Android app 3.62.4 sends these headers, although the server doesn't seem to care"""

BASE_URL = 'https://app-prod.mysa.cloud'
"""Base URL for Mysa's JSONful API"""


def auther(u):
    def f(request: requests.Request) -> requests.Request:
        if time() > u.id_claims['exp'] - 5:
            u.renew_access_token()  # despite the name, this also renews the id_token

        # It's a JWT, a bearer token, which means we *should* prefix it with "Bearer" in the
        # authorization header, but Mysa servers don't seem to accept it with the
        # "Bearer" prefix (although they seemingly used to: https://github.com/drinkwater99/MySa/blob/master/Program.cs#L35)
        request.headers['authorization'] = u.id_token
        return request
    return f


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


@dataclass
class MysaReading:
    '''Binary structure representing one raw reading from a Mysa thermostat device.
    There are several versions/variants of this structure.

    All of them appear to share a certain set of fields and meanings, but they vary
    in additional fields and overall length.'''
    ver: int                  # LEADING version byte, overridden in child classes
    ts: int                   # Unix time (seconds)
    sensor_t: float           # Unit = °C
    ambient_t: float          # Unit = °C
    setpoint_t: float         # Unit = °C
    humidity: int             # Percent
    duty: int                 # Percent
    on_ms: int                # Unit = 1 ms
    off_ms: int               # Unit = 1 ms
    heatsink_t: float         # Unit = °C
    free_heap: int            # Free heap (what IS this?)
    rssi: int                 # Unit = 1 dBm; frequently-but-not-always (???) stuck at 1 for BB-V2-0(-L) devices
    onoroff: int              # Probably boolean, not int
    checksum: int             # Final byte (simple XOR checksum of preceding)
    checksum_good: bool
    unknown: Optional[bytes]  # Bytes before final checksum, overridden in child classes

    @classmethod
    def parse_readings(cls, readings: bytes) -> list['MysaReading']:
        global _known_reading_vers
        offset = 0
        assert len(readings) >= 26
        ver = readings[2]
        output = []
        while offset < len(readings):
            _start = offset
            assert readings[offset: offset+2] == b'\xca\xa0' # All should have same prefix
            assert readings[offset+2] == ver                 # ... and same version
            offset += 3
            sts, sens, amb, setp, hum, duty, onish, offish, heatsink, heap, rssi, onoroff = struct.unpack_from('<LhhhbbhhhHbb', readings, offset)
            offset += 22
            heap *= 10                                          # On-the-wire unit = 10 (10 what??)
            sens /= 10; amb /= 10; setp /= 10; heatsink /= 10   # On-the-wire unit = 0.1°C
            rssi = -rssi                                        # On-the-wire-unit = -1 dBm
            onish *= 100; offish *= 100                         # On-the-wire-unit = 100 ms
            args = [sts, sens, amb, setp, hum, duty, onish, offish, heatsink, heap, rssi, onoroff]

            if _cls := _known_reading_vers.get(ver):
                rest, offset = _cls._unpack_rest(readings, offset)
                unknown = None
            else:
                # Find the start of the next reading for an *unknown* version. Hopefully there are
                # no inadvertent matching bytes!!
                if (end := readings.find(bytes((0xca, 0xa0, ver)), offset + 1)) < 0:
                    end = len(readings)
                unknown = readings[offset: end-1] if end > offset + 1 else None
                _cls = cls

            csum = readings[offset]
            offset += 1
            csum_good = reduce(int.__xor__, readings[_start: offset]) == 0

            output.append(_cls(
                ver=ver, ts=sts, sensor_t=sens, ambient_t=amb, setpoint_t=setp, humidity=hum, duty=duty,
                on_ms=onish, off_ms=offish, heatsink_t=heatsink, free_heap=heap, rssi=rssi, onoroff=onoroff,
                unknown=unknown, checksum=csum, checksum_good=csum_good, **rest))
            #assert bytes(reading) == readings[_start: offset], f'\n{bytes(reading)} != \n{readings[_start: offset]}'
        return output

    def _pack_rest(self):
        return self.unknown or b''

    def __str__(self):
        if not self.checksum_good:
            checksum_right = reduce(int.__xor__, bytes(self)[:-1])
        return (f'{datetime.fromtimestamp(self.ts)}: sens={self.sensor_t:.1f}°C, amb={self.ambient_t:.1f}°C, setp={self.setpoint_t:.1f}°C, '
                f'hum={self.humidity}%, dty={self.duty}%, on?={self.on_ms}ms, off?={self.off_ms}ms, heatsink={self.heatsink_t:.1f}°C, '
                f'freeheap={self.free_heap}, rssi={self.rssi}{"" if self.rssi is None else "dBm"}, onoroff={self.onoroff}'
                + ('' if self.unknown is None else f', ?unknown?={self.unknown.hex()}')
                + f', checksum={self.checksum:02x}' + ('' if self.checksum_good else f' ! should be {checksum_right:02x}!'))

    def __bytes__(self):
        b = b'\xca\xa0' + struct.pack('<bLhhhbbhhhHbb', self.ver, self.ts,
            int(self.sensor_t * 10), int(self.ambient_t * 10), int(self.setpoint_t * 10),  # On-the-wire unit = 0.1°
            self.humidity, self.duty,
            self.on_ms // 100, self.off_ms // 100,  # On-the-wire-unit = 100 ms
            int(self.heatsink_t * 10),              # On-the-wire unit = 0.1°C
            self.free_heap // 10,                   # On-the-wire unit = 10 (of something)
            -self.rssi,                             # On-the-wire unit = -1 dBm
            self.onoroff) + self._pack_rest()
        # FIXME: setting checksum=None forces it to be recalculated
        b_cs = bytes((reduce(int.__xor__, b) if self.checksum is None else self.checksum,))
        return b + b_cs


@dataclass
class MysaReadingV0(MysaReading):
    '''Version 0 binary structure representing one raw reading from a Mysa thermostat device.

    This version is used by the thermostat with model number BB-V1-1 ("Mysa Baseboard V1"),
    and maybe others.'''
    @classmethod
    def _unpack_rest(cls, readings: bytes, offset):
        return {}, offset

@dataclass
class MysaReadingV1(MysaReading):
    '''Version 1 binary structure representing one raw reading from a Mysa thermostat device.

    This version is used by the thermostat with model number INF-V1-0 ("Mysa Floor"),
    and maybe others.'''
    voltage: int      # Unit = 1 V

    @classmethod
    def _unpack_rest(cls, readings: bytes, offset):
        voltage, = struct.unpack_from('<h', readings, offset)
        return {'voltage': voltage}, offset + 2

    def _pack_rest(self):
        return struct.pack('<h', self.voltage)

    def __str__(self):
        return super().__str__() + f' | v1: voltage={self.voltage}V'


@dataclass
class MysaReadingV3(MysaReading):
    '''Version 3 binary structure representing one raw reading from a Mysa thermostat device.

    This version is used by the thermostats with model number BB-V2-0 ("Mysa Baseboard V2")
    and BB-V2-0-L ("Mysa V2 Lite"), and maybe others.'''
    voltage: int      # Unit = 1 V
    current: int      # Unit = 1 mA
    always0: bytes    # Unknown 3 bytes, seemingly always zero

    @classmethod
    def _unpack_rest(cls, readings: bytes, offset):
        voltage, current, always0 = struct.unpack_from('<hh3s', readings, offset)
        current *= 10                           # On-the-wire unit = 10 mA
        return {'voltage': voltage, 'current': current, 'always0': always0}, offset + 7

    def _pack_rest(self):
        return struct.pack('<hh3s', self.voltage,
            self.current // 10,  # On-the-wire unit = 10 mA
            self.always0)

    def __str__(self):
        return super().__str__() + f' | v3: voltage={self.voltage}V, cur={self.current}mA, zero?={self.always0.hex()}'


_known_reading_vers = {
    0: MysaReadingV0,
    1: MysaReadingV1,
    3: MysaReadingV3,
}
