import pycognito
import requests
import pytz
from time import time
from datetime import datetime

from argparse import ArgumentParser
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


u = pycognito.Cognito(
    user_pool_id='us-east-1_GUFWfhI7g',
    client_id='19efs8tgqe942atbqmot5m36t3',
    username=args.user)
u.authenticate(password=args.password)

assert u.token_type == 'Bearer'
s = requests.Session()
s.headers.update({
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

devices = s.get(f'{BASE_URL}/devices').json(object_hook=slurpy).DevicesObj
states = s.get(f'{BASE_URL}/devices/state').json(object_hook=slurpy).DeviceStatesObj
firmware = s.get(f'{BASE_URL}/devices/firmware').json(object_hook=slurpy).Firmware
# Have also seen:
#   GET /devices/capabalities (empty for me)
#   GET /devices/drstate (empty for me)
#   GET /homes, /homes/{home_uuid}, /users, /users/{user_uuid}, /schedules, etc (-> JSON)
#   PATCH /users/{user_uuid} (-> set app info)
#   POST /energy/setpoints/device/{device_id} (-> mystifyingly, this is NOT setting the device setpoint, only reading it?? payload={"PhoneTimezone": "America/Vancouver", "Scope": "Day","Timestamp": 1736700658}

for did, d in devices.items():
    assert did == d.Id
    print(f'{d.Name} (model {d.Model!r}, id {d.Id!r}, firmware {firmware[did].InstalledVersion}):')
    tz = pytz.timezone(d.TimeZone)
    if did not in states:
        print('  No state found!')
    else:
        s = states[did]
        # s.Timestamp seems to be the "power-up time" of the device
        ts = 0
        width = max(len(k) for k in s)
        for k, vd in sorted(s.items()):
            if not isinstance(vd, dict):
                continue

            if vd.t > 1000<<30:
                vd.t /= 1000   # sometimes ms, sometimes seconds!? insane
            if vd.t > ts:
                ts = vd.t

            if vd.v == -1:
                vd.v = None

            if k in ('SensorTemp', 'CorrectedTemp', 'SetPoint', 'HeatSink'):
                if d.Format == 'fahrenheit':
                    v = f'{32+vd.v*9/5:.1f}°F'
                else:
                    v = f'{vd.v}°C'
            elif k in ('Humidity', 'Brightness'):
                v = f'{vd.v}%'
            else:
                v = vd.v

            print(f'  {k+":":{width+1}} {v}')
        else:
            ts = datetime.fromtimestamp(ts, tz=tz)
            print(f'  Last update at {ts.isoformat()}')
