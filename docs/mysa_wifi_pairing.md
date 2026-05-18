# Mysa WiFi pairing

Mysa devices boot into [pairing mode](https://web.archive.org/web/20260117035829/https://help.getmysa.com/en-US/mysa-pairing-378302)
when first powered-on, and can be put back into this mode by holding their
temperature up/down buttons for about 10 seconds.[^0]

In pairing mode, the device loses its network connection and forgets all of its
local settings (brightness, units, etc.), but it does not lose its association
with a Mysa cloud account, and once it can reconnect to the Mysa cloud server
it re-syncs its settings.

While in pairing mode the thermostat device creates a 2.4 GHz wireless AP with
SSID of `Mysa-$DID6`, and serves unencrypted HTTP on `http://192.168.4.1:57961`,[^1]
while displaying a triangle symbol for older models, or the Bluetooth symbol
for newer ones.[^2]

[^0]: They can also be put back into pairing mode by sending a
  specially crafted MQTT payload that I dubbed ["killer ping"](mysa_messages.md#killer-ping),
  although that's probably a bit too scary-sounding of a name since the
  device is not in any way permanently disabled, and the user must be authenticated
  as a device owner now that they fixed [the major server-side vulnerability
  that I reported](https://snowpatch.org/posts/i-can-completely-control-your-smart-thermostat/).
[^1]: Some devices also serves an Apple HomeKit service on port 57959
  *while in pairing mode*. This is a separate complex protocol for purely
  LAN-based control of the device, which is already well-understood
  by HomeAssistant. Running the HomeKit service *while in pairing
  mode* seems to be an oversight by Mysa, however. The HomeKit service cannot
  actually function until the device has connected to the home
  WiFi network.
[^2]: The newer devices/firmwares which support Bluetooth pairing also support
  WiFi pairing while the Bluetooth pairing icon is visible.
  The Bluetooth LE pairing protocol is easy to capture with Android btsnoop,
  is really quite similar to what's described here, and doesn't seem to offer
  any intriguing capabilities.

## Supported requests

The pairing-mode HTTP server supports the following requests, whose effects
can be summarized briefly:

- `GET /hwid` → `{"hwid": "$DID6"}`
- `GET /model` → `{"model": "$MODEL"}`
- `GET /identify` → `{"status": "ok"}`, and causes the device to flash a smile
  symbol on its screen for a few seconds.
- `GET /pubkey` -> returns a PEM-formatted 2048-byte RSA public key
- `GET /connected`:
  - While waiting for network details: 202, `{"status": "connection in progress"}`
  - If it couldn't connect via the network details provided: 400, `{"error": "could not find or connect to network"}`
  - If it successfully connected: 200, `{"status": "ok"}`
- `GET /networks`:
  - Causes the device to scan for visible networks, and then after 10+ seconds to return a list of them
  - `[{"ssid":"foo","rssi":-39},{"ssid":"foo2","rssi":-52},...,{"ssid":"baz","rssi":-95}]`
  - Seemingly buggy on older firmware, and sometimes just returns `[]`
- `GET /network/`
  - Provides WiFi network details to the device, details [below](#providing-wifi-network-details).
- `GET /reboot`:
  - If the device has successfully connected to a WiFi network, causes the
    device to disable the pairing-mode AP and commence normal operation as a WiFi client
  - Socket hangs forever and never returns
- `GET /certificates`, `PUT /certificates/{0,1}`
  - Manipulates the device's TLS trust store, very gory details [below](#certificates-endpoint)

## Providing WiFi network details

In order to connect the device to a WiFi network,
the pairing app creates a JSON blob containing the connection details and
encrypts them with the device's public key (from `GET /pubkey`) and PKCS #1 v1.5 padding.[^4]

[^4]: This is intended to prevent the network password from being
  captured with passive network snooping, and it seems at first glance to be
  adequate for this purpose although [rolling your own crypto
  protocol](https://security.stackexchange.com/questions/18197) is an obvious
  minefield and I wouldn't at all be surprised if there's (say) a timing attack
  to recover the Mysa device's internally-generated RSA private key.\
  \
  In any case, it does nothing to protect against a MITM attacker that can
  generate its own RSA keypair, run its own HTTP pairing server, and relay
  the credentials to the real Mysa device.

Then it plunks this JSON blob into the `mysa-data` header in a `GET /network` HTTP query.

A normal computer can easily perform this WiFi connection process
by connecting to the Mysa device's temporary access point, and then
running [this Bash script](mysa-wifi-pair.sh), which boils down to:[^5]

1. Put `{"ssid":"SSID","pass":"p@ssw0rd"}` in `wifi_config.json`
2. Combine `curl`, `openssl rsautl`, and `base64` into this ghastly two-liner:
   ```sh
   curl -s 'http://192.168.4.1:57961/network/' \
     -H "mysa-data: $(curl -s 'http://192.168.4.1:57961/pubkey'|openssl rsautl -encrypt -pubin -inkey /dev/stdin -in wifi_config.json -pkcs|base64 -w0)"
   ```

After sending the connection details, there is a delay of 5-10 second
while the device attempts the connection, then switches back to AP mode,
and then responds with 200 `{"status": "ok"}`, though this
*doesn't actually indicate "success"*; it's still necessary to
check `/connected`.

It responds 400 `{"error": "didn't receive ssid and/or password"}` if
the JSON payload of `mysa-data` was malformed… but only up to a point. If
the header is absent, the device unceremoniously crashes and a watchdog
timer reboots it back into pairing mode after a few seconds.

[^5]: In fact, given how slow and unreliable Android IoT apps are at doing
this AP-based WiFi pairing dance, this is by far the *most reliable* way
to connect a Mysa thermostat to a WiFi network, which is especially handy when
experimenting with the devices and frequently resetting them into pairing mode.

## Certificates endpoint

This _only exists_ in newer versions of the firmware[^6]:

[^6]: `GET /certificates` seems to have been added in 3.16.0.4; `PUT /certificates/{0,1}` in 3.16.0.6.

`GET /certificates` → `{"certificates": ["1d978c...", "cbeea2..."]}`

These hexadecimal strings are sha256 digests of two TLS root CA
certificates:

1. https://crt.sh/?sha256=1465fa205397b876faa6f0a9958e5590e40fcc7faa4fb7c2c8677521fb5fb658 (Starfield Class 2 CA root)
   - This is the root CA cert for TLS on `a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com` (ports 8883 and 443),
     as well as `devices10010.getmysa.com:443`
2. https://crt.sh/?sha256=4348a0e9444c78cb265e058d5e8944b4d84f9662bd26db257f8934a443c70161 (DigiCert Global Root CA)
   - This is the root CA cert for TLS on `devices10010b.mysa.cloud:443`

… but they are *not* hashed in the sane/standard way of hashing X.509
certificates (in their DER-encoded/binary form):

Rather they are the sha256 digests of the certs encoded as **PEM** (with 64 base64 chars/line, `\n` as
EOL delimiter, standard `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----`
as first and last lines, but ⁉️ _no final newline_).

You can verify the mapping from the sane/standard sha256 digest of these certificates
to their bizarro Mysa sha256 digests with:

```sh
curl 'https://crt.sh/?d=$SHA256' | \
  openssl x509 -outform PEM | perl -pe 'chop if /END CERTIFICATE/' | sha256sum
```

### Replacing certificates

| ⚠️ Don't do this: Here there be dragons 🐲 |
| ------------------------------------------ |
| If you replace the root certificates trusted by the Mysa device, it will no longer connect to Mysa cloud services. Even if you restore the original certificates, it may take _days_ until the device starts *reliably* connecting to cloud services again, due to the caching bugs mentioned below.

Replacement certificates can be uploaded into the two "slots" with `PUT /certificates/{0,1}`. After
uploading a new cert, this time _**in DER-encoded/binary form**_, its hash is reflected in the
`GET /certificates` output:

```sh
$ openssl x509 -outform DER < some_cert.pem | curl -v -X PUT 'http://192.168.4.1:57961/certificates/1' -H 'Expect: ' --data-binary @/dev/stdin
{"status": "ok"}
$ curl http://192.168.4.1:57961/certificates
{"certificates": ["1d978c9bdd1b95b46bc007e7779d2bb1d655af49d18afb4e0d8a7ee68244a1a2", "deadbeefcafef00fdeadbeefcafef00fdeadbeefcafef00fdeadbeefcafef00f"]}
```

After the certificates are replaced, and the device is [reconnected to WiFi](#providing-wifi-network-details),
it will start *refusing to connect* to the normal servers in the AWS cloud,
due to TLS root certificate mismatch. It will *eventually* start expecting
different root certificates for these TLS servers:

- `devices10010.getmysa.com:443`
- `a3q27gia9qg3zy-ats.iot.us-east-1.amazonaws.com` (ports 8883 and 443)
- `devices10010b.mysa.cloud:443`

At least with the firmware versions that I've tested, it takes an
agonizingly long time for this change to "take," many hours to days.
This is probably because of bugs in how TLS certificates are cached in
various corners of RAM and NVM by the device firmware.

### The implications of this

The ability to replace the trusted root certificates provides a path to
[sever the Mysa devices from the cloud servers that the company uses](../README.md#future),
and replace them with something running locally, although it's a very slow
and fiddly process due to those caching bugs.[^7]

[^7]: Mysa clearly foresees the eventual future need to update the devices'
  root CA certificates, because they added these endpoints to the WiFi pairing
  server in 2024-2025, but they don't appear to have ironed out the caching
  bugs yet.
