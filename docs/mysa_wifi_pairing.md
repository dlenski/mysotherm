# Mysa wifi pairing

While in [pairing mode](https://help.getmysa.com/en-US/mysa-pairing-378302),
the thermostat device creates a wireless AP with SSID of `Mysa-$DID6`,
and serves HTTP on `http://192.168.4.1:57961`.

- Even newer devices/firmwares which advertise Bluetooth pairing also support WiFi pairing when
  the Bluetooth pairing icon is visible. (The Bluetooth LE pairing protocol is really quite
  similar.)
- Device also serves Apple HomeKit pairing server on port 57959 while in pairing mode.
  That's a separate complex protocol already well-understood by HomeAssistant.

## Supported requests

- `GET /hwid` -> `{"hwid": "$DID6"}`
- `GET /model` -> `{"model": "$MODEL"}`
- `GET /identify` -> `{"status": "ok"}` and causes the device to flash a "smile" on its screen
- `GET /pubkey` -> PEM-formatted 2048-byte RSA public key
- `GET /connected`:
  - While waiting for network details: 202, `{"status": "connection in progress"}`
  - If it couldn't connect via the network details provided: 400, `{"error": "could not find or connect to network"}`
  - If it successfully connected: 200, `{"status": "ok"}`
- `GET /networks`:
  - Causes device to scan for visible networks, and then after ~10+ seconds to return a list of them
  - `[{"ssid":"foo","rssi":-39},{"ssid":"foo2","rssi":-52},...,{"ssid":"baz","rssi":-95}]`
  - Buggy on older firmware, and sometimes just returns `[]`
- `GET /network/`
  - Provides WiFi network details to the device, details below
- `GET /certificates`, `PUT /certificates/{0,1}`
- `GET /reboot`:
  - Causes device to disable the pairing-mode AP and commence normal operation as a WiFi client
  - Socket hangs forever and never returns

## Providing wifi network details

The pairing app creates a JSON blob containing the connection details and
encrypts them with the device's public key (from `GET /pubkey`) and PKCS #1 v1.5 padding.

Then it plunks this JSON blob into the `mysa-data` header (!?!?!) in a `GET /network` HTTP query.

```sh
$ echo '{"ssid":"SSID","pass":"p@ssw0rd"}' > wifi_config.json
$ curl -s 'http://192.168.4.1:57961/network/' \
  -H "mysa-data: $(curl -s 'http://192.168.4.1:57961/pubkey'|openssl rsautl -encrypt -pubin -inkey /dev/stdin -in wifi_config.json -pkcs|base64 -w0)"
# delay of 5-10 seconds while device attempts connection (and then recreates AP?), and then...
400 {"error": "didn't receive ssid and/or password"}   # if malformed
200 {"status": "ok"}                                   # doesn't actually indicate "success", still need to check /connected
<device freezes and reboots after a few seconds>       # if mysa-data not provided
```

## Mysterious certificates endpoint

This _only exists_ in newer versions of the firmware (`GET /certificates` added in 3.16.0.4; `PUT /certificates/{0,1}` added in 3.16.0.6).

`GET /certificates` ->
```json
{"certificates": ["1d978c9bdd1b95b46bc007e7779d2bb1d655af49d18afb4e0d8a7ee68244a1a2", "cbeea2a34b6c7b2c7df9ae0f99d7b5cf580f50bb49352614a46fd816461a30a5"]}
```

These are sha256 digests, and are the same across all devices on firmware 3.16.2.3.
They are *not* the sha256 digests of the DER-encoded/binary form of the certs, but
rather they are the sha256 digests of the certs encoded as **PEM** (with 64 base64 chars/line, `\n` as
EOL delimiter, _no final newline_, standard `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----`
as first and last lines):

1. https://crt.sh/?sha256=1465fa205397b876faa6f0a9958e5590e40fcc7faa4fb7c2c8677521fb5fb658 (Starfield Class 2 CA root)
  - This is the root cert that signs TLS on `a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com` (ports 8883 and 443),
    as well as `devices10010.getmysa.com:443`
2. https://crt.sh/?sha256=4348A0E9444C78CB265E058D5E8944B4D84F9662BD26DB257F8934A443C70161 (DigiCert Global Root CA)
  - This is the root cert that signs TLS on `devices10010b.mysa.cloud:443`

You can check these with `curl 'https://crt.sh/?d=$SHA256' | perl -pe 'chop if /END CERTIFICATE/' | sha256sum`.

There are two "slots" to upload new certs (0 and 1), with `PUT /certificates/{0,1}`. After
uploading a new cert in DER form, its hash is reflected in the `GET /certificates` output:

```sh
$ openssl x509 -outform DER < some_cert.pem | curl -v -X PUT 'http://192.168.4.1:57961/certificates/1' -H 'Expect: ' --data-binary @/dev/stdin
{"status": "ok"}
$ curl http://192.168.4.1:57961/certificates
{"certificates": ["1d978c9bdd1b95b46bc007e7779d2bb1d655af49d18afb4e0d8a7ee68244a1a2", "deadbeefcafef00fdeadbeefcafef00fdeadbeefcafef00fdeadbeefcafef00f"]}
```

⚠️⚠️⚠️ Replacing `/certificates/1` with a MITM CA cert does not have any effect I can discern;
the device still connects to the same MQTT server and still aborts if it doesn't match the
pinned cert details.

☠️☠️☠️ Replacing `/certificates/0` with a MITM CA cert _entirely stops the device from
connecting to the MQTT server_, thus disabling almost all of its useful functionality,
and the only way I can figure out to restore it is to force a downgrade to an older
firmware version, 3.13.1.25, where _the HTTP endpoints for `/certificates` don't exist_.
