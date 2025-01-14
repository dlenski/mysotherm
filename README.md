# mysotherm

[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Inspect and (hopefully soon!) manipulate Mysa smart thermostats.

# Motivation

[Mysa](https://getmysa.com) is a Canadian company that makes nice-looking smart thermostats.
They're subsidized and promoted by utility companies including [BC Hydro](https://bchydro.com).

They have free Android and iOS apps, and they apparently integrate with other home automation
stuff that I know nothing about and have never used.

My concerns:

- The app claims to have
  ["No fees (for real). All the features."](https://getmysa.com/pages/app-ca#:~:text=Free%20app.%20No%20fees%20(for%20real).%0AAll%20the%20features.)
  but if you have their more inexpensive Mysa Lite device then you don't get in-app charting,
  energy cost reports, or multi-zone control, despite the fact that those appear to be
  _entirely software-based_ features.
- The devices appear to be entirely "cloud-dependent": communication with the thermostats goes through
  AWS cloud services and there is no known
  [local network API](https://www.reddit.com/r/smarthome/comments/18z22f0/mysa_thermostat_lan_api/)
- And most importantly, I just want to know how they work 🕵🏻‍♂️

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

- The Cognito authentication is still the same
- The HTTP API for reading the devices has been replaced with a bunch of new JSONful
  endpoints: `GET /devices/state`, `GET /users`
- The MQTT API for "real-time" communication with the devices is probably still
  similar
