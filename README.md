# mysotherm

[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Inspect and manipulate Mysa smart thermostats.

# Motivation

[Mysa](https://getmysa.com) is a Canadian company that makes nice-looking smart thermostats.
They're subsidized and promoted by utility companies including [BC Hydro](https://bchydro.com).

They have free Android and iOS apps, and they apparently integrate with other home automation
stuff that I know nothing about and have never used.

My concerns:

- The app claims to have
  ["No fees (for real). All the features."](https://getmysa.com/pages/app-ca#:~:text=Free%20app.%20No%20fees%20(for%20real).%0AAll%20the%20features.)
  but if you have their more inexpensive Mysa Lite device then you don't get in-app charting of temperature and energy usage
  or multi-thermostat zone control, despite the fact that those appear to be _entirely software-based_ features.
- The devices appear to be entirely "cloud-dependent": communication with the thermostats goes through
  AWS cloud services and there is no known
  [local network API](https://www.reddit.com/r/smarthome/comments/18z22f0/mysa_thermostat_lan_api/)
- The first one I bought was a Mysa Lite which had [a stuck-open
  relay](https://electronics.stackexchange.com/questions/736103/cleaning-a-stuck-open-relay-thats-mounted-on-a-pcb) (yes, really) and I was tearing
  my hair out trying to figure out what was wrong with it.
- And most importantly, I want to know how they work 🕵🏻‍♂️

# Prior work

Back in 2020, https://github.com/fdurand/mysa-thermostats showed how to authenticate
to the Mysa cloud service (it's [AWS Cognito](https://aws.amazon.com/cognito)) and how to
query the thermostat readings (`https://app-prod.mysa.cloud/users/readingsForUser`).
https://github.com/fdurand/mysa-thermostats/issues/1#issuecomment-750362234 also
demonstrated that _setting the thermostat_ is done via a separate API (MQTT over
websocket to an AWS IoT server).

# Current status

The API discovered in 2020 seems to have corresponded to Mysa's Android app 2.82, and
no longer works (HTTP `500`) with 2024-2025 versions of the app.

The Cognito authentication is still the same, but the HTTP API for reading the devices
has been replaced with a bunch of new JSONful endpoints: `GET /devices/state`, `GET /users`

In January 2025, I figured out
[how to authenticate to the MQTT-over-WebSockets endpoint used by the app](https://github.com/dlenski/mysotherm/commit/297df32303ba1db5edcdb21cac3db9a5c4bf5013);
the short summary is that Mysa is doing the AWS SigV4 "URL presigning" in an unusual
and potentially insecure way.

I've figured out what most of the MQTT messages sent between the app and the thermostats mean.
See [mysa_messages.md](./mysa_messages.md) for some semi-structured notes.

## Inspecting Mysa thermostat devices

Check out this repository, and then use [`poetry install`](https://python-poetry.org) to install
the required Python dependencies. Then you can inspect much of the interesting data stored
for your thermostats with the login credentials that you use for the Mysa app:

```
poetry run mysotherm
No Mysa login credentials found in ~/.config/mysotherm
Username: who.ever@email.com
Password: ********
```

After running for the first time, `mysotherm` will cache your Mysa
authentication tokens (but _not_ your literal password) in
`~/.config/mysotherm`, and won't prompt you for them again unless they
expire (which will only happen if you don't use them for about a month).

It should be pretty easy to add setpoint-adjusting and schedule-creating features
to the CLI as well; I just haven't gotten around to it.

(I only own Mysa Baseboard V1 and V2 Lite devices. Would be very interested to learn
if other devices have other kinds of data.)

## "Magically upgrade" your Mysa V2 Lite thermostats

The Mysa V2 Lite is the most inexpensive and compact thermostat device that Mysa sells.
Unlike the Mysa V1 which uses a triac to control baseboard heater current, the V2 devices
use a simple relay; the Mysa V2 Lite also lacks a _current sensor_.

However, many of the restrictions of the device appear to be purely software-based.
With Mysa V2 Lite, you don't get:

- In-app charting of temperature or energy usage (even without a current sensor, it
  should still be possible to get a pretty good estimate of energy usage simply by
  asking the user to input the heater's peak power or current).
- Multi-thermostat zone control, which appears _entirely software-based_.
- Humidity sensor output: to my surprise, the Mysa V2 Lite appears to contain a
  perfectly functional humidity sensor even though it's not advertised as such.

Using the `liten-up` tool, you can "magically upgrade" your Mysa V2 Lite thermostat:
this script tricks the app into thinking your device is a Mysa V1 thermostat, and
then does a two-way translation of the slightly-incompatible messages sent by the
device and the app into the correct formats.

Run with:
```
poetry run liten-up --current 5.67
```

The `--current` option specifies the estimated current, in Amperes, drawn by
your Mysa V2 Lite device(s). If provided, this will inform the energy usage
shown in the app.

While running, the official Mysa smartphone apps will show humidity sensor,
zone control, and usage statistics for your Mysa V2 Lite devices.

When you interrupt the program, it will attempt to "restore" the Mysa V2 Lite
thermostats to their original state. (And you can `poetry run liten-up --reset`
to do this by itself.)

# Future?

In order to de-cloud-itate these devices, and prevent them from the inevitable
future bitrot/bricking, it'll likely be necessary to overcome their
[certificate pinning](https://docs.mitmproxy.org/stable/concepts-certificates/#certificate-pinning).

# Credits

- https://github.com/fdurand/mysa-thermostats for figuring out much of the auth
  details back in 2022.
- Me, for figuring out the MQTT-over-WebSockets auth
- https://github.com/mitmproxy/mitmproxy and https://github.com/nikitastupin/mitmproxy-mqtt-script
  for making it easy to MITM the traffic to/from the devices

# License

GPLv3 or later
