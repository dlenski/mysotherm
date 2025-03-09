# Mysa MQTT messages

- `DID` is the 12-digit MAC address of the device.
- MQTT topics are `/v1/dev/$DID/{out,in}`
- `UNIXTIME` is in seconds, `UNIXTIMEMS` is in milliseconds
- `USER_UUID` is the UUID associated with a user account (seen in `/users` response
- `HOME_UUID` is the UUID associated with a home (seen in `/homes` response
- `MODEL` is `BB-V1-1` (Mysa V1 Baseboard), `BB-V2-0-L` (Mysa V2 Lite), `BB-V2-0` (Mysa V2 Baseboard), etc.

## Solicit thermostat state information

Sent by app to `/v1/dev/$DID/in` with QOS=1:

```json
{"Device": "$DID",
 "MsgType": 11,
 "Timeout": 180,
 "Timestamp": $UNIXTIME}
 ```

 … and this should cause the device to report its state promptly.

## Device state

### BB-V1-1 thermostats

Sent by thermostat to `/v1/dev/$DID/out` with QOS=0:

```json
{"ComboTemp": 20.93,          # I think this is "SensorTemp" in /devices/state
 "Current": 0.0,              # This seems to be "the current right now" as opposed to "the highest current seen" reported in /devices/state; "DutyCycle" in /devices/state is the ratio of the two
 "Device": "$DID",
 "Humidity": 48.0,
 "MainTemp": 17.15,           # I think this is "CorrectedTemp" in /devices/state
 "MsgType": 0,
 "SetPoint": 15.5,
 "Stream": 1,
 "ThermistorTemp": 0.0,
 "Timestamp": $UNIXTIME}
 ```

The `Duty` value in `/devices/state` is very laggy compared to the `Current` seen here.

### BB-V2-0-L thermostats

Sent by thermostat to `/v1/dev/$DID/out` with QOS=0:

```json
{"body": {"ambTemp": 16.7,   # I think this is "CorrectedTemp" in /devices/state
          "dtyCycle": 1.0,   # = 1.0 when relay is on, 1.0 when off
          "hum": 48.0,
          "stpt": 17.8
          },
 "id": ${large random number},     # 64-bits long?
 "msg": 40,
 "src": {"ref": "$DID", "type": 1},
 "time": $UNIXTIME,
 "ver": "1.0"}
```

**Mystery**: Unlike the V1 devices, above, there's no field in this output which appears
to contain the uncorrected sensor temperature. Yet this device's uncorrected
sensor temperature does appear in the `/devices/state` output; where does it come from?

**Gripe**: The `Duty` value in `/devices/state` is very laggy compared to the `dtyCycle`
seen here.

## Check your settings

Sent by app to `/v1/dev/$DID/in` with QOS=1. Appears to indicate to the thermostat
that it should check its "non-realtime" settings via the `/devices/state` API:

```json
{"Device": "$DID",
 "EventType": 0,
 "MsgType": 6,
 "Timestamp": $UNIXTIME}
```

Settings that you can change in this way include the following (you'll
need to include the `-H 'Authorization: $TOKEN'` header as well):

```
curl /devices/$DID -d '{"MinBrightness": $N}'
curl /devices/$DID -d '{"MaxBrightness": $N}'
curl /devices/$DID -d '{"AutoBrightness": {true,false}}'   # Only for Mysa V2
curl /devices/$DID -d '{"ProximityMode": {true,false}}'    # Only for Mysa V2
curl /devices/$DID -d '{"Format": "{celsius,fahrenheit}"}'
curl /devices/$DID -d '{"ecoMode": "{0,1}"}'   # Weirdly, 0 is on, 1 is off
curl /devices/$DID -d '{"Name": "$WHATEVER"}'
curl /devices/$DID -d '{"TimeZone": "$WHATEVER"}'
```

## Dump your readings

Appears to indicate to the thermostat that it should immediately dump its readings in the binary format
(see [below](#readings-from-device)):

```json
{"Device": "$DID",
 "Timestamp": $UNIXTIME,
 "MsgType": 7}
```

### Magic upgrade

The most fascinating "settings change" you can make is that you can
"upgrade" your `BB-V2-0-L` (Mysa Lite) to a `BB-V2-0` (Mysa V2) with
`curl /devices/$DID -d '{"Model": "BB-V2-0"}'`. After making
this change the app will show a bunch of features that the Mysa Lite
supposedly doesn't have:

1. Humidity sensor (appears to physically exist on the device, may be uncalibrated!)
2. Proximity sensor (physically nonexistent)
3. Zone control
  - Mysa says their app is 100% free, but they're locking out this pure-software feature for the lowest-cost device 😤)
4. Usage graph
  - It shows setpoint, humidity, and ambient temperature
  - It doesn't show usage/cost due to the absence of the expected current sensor
  - If Mysa _wanted_ to implement this properly, they could still show usage based on duty cycle of the relay

The _huge caveat_ of this is that the thermostat can't be adjust via the app as long
as the "magic upgrade" is in place. This appears to be due to slightly different signalling
used to send setpoint updates for different models. (See "Change setpoint or mode" below.)

## Unknown

Sent by thermostats (both v1 and v2?) to `/v1/dev/$DID/out` with QOS=1, seemingly
after the setpoint has changed?

```json
{"Device": "$DID",
 "MsgType": 1,
 "Next": 18.5,
 "Prev": 21.0,
 "Source": 3,
 "Timestamp": $UNIXTIME}
 ```

Sent by cloud/server (maybe?) to `/v1/dev/$DID/in`, unclear when/why… maybe when device appears to have lost connectivity?

 ```json
{"Device": "$DID",
 "MsgType": 20,
 "Timestamp": 1234}   #<-- Relatively low value
 ```

## "Killer ping""

Sending this to `/v1/dev/$DID/in` leads to a reply, and then the device restarts in pairing mode (!!) about 30 seconds later:

```json
{"Device": "$DID",
 "Timestamp": $UNIXTIME,
 "MsgType": 40, "EchoID": $X}
```

The reply:

```json
{"Device": "$DID",
 "Timestamp": $UNIXTIME,
 "MsgType": 5,
 "EchoID": 1}
```

Other *small* values of EchoID give similar results:

* 0, 1 -> restarting in pairing mode without error status
* 2 or 3 -> restarting in pairing mode *and* show [H2 error](https://help.getmysa.com/en-US/error-code-h2-257246)

## Generic device log message

Sent by devices to `/v1/dev/$DID/out` with QOS=0. Unsure what triggers it, but happens at boot and sometimes to
report local IP, serial number (!= device ID, otherwise hidden???), and firmware version:

```json
 {"Device": "$DID",
 "Level": "INFO",
 "Message": "api got version 3.16.2.3",
 "MsgType": 4,
 "Timestamp": $UNIXTIME}
```

 ## Change setpoint or mode

Sent by app to `/v1/dev/$DID/in` with QOS=1:

- `TYPE` is 1 for `BB-V2-0`, 4 for `BB-V2-0`, and 5 for `BB-V2-0-L`
- **_Devices don't seem to respond to this command if it has the wrong type value for the device_**

```json
{"Timestamp": $UNIXTIME,
 "body": {"cmd": [{"sp": 17, "tm": -1}], "type": $TYPE, "ver": 1},  # sometimes also sent in a derpy version where cmd has been wrapped in a string
 "dest": {"ref": "$DID", "type": 1},
 "id": $UNIXTIMEMS,
 "msg": 44,
 "resp": 2,
 "src": {"ref": "$USER_UUID", "type": 100},
 "time": $UNIXTIME,
 "ver": "1.0"}
```

Thermostat responds on `/v1/dev/$DID/out` with QOS=0:

```json
{"body": {"state": {"br": 50, "ho": 1, "lk": 0, "md": 3, "sp": 17.0},
          "success": 1,
          "trig_src": 3,   # response to 3=app command, 1=button command
          "type": 5},
 "id": ${large random number},     # 64-bits long?
 "msg": 44,
 "resp_id": ${id from request},
 "src": {"ref": "$DID", "type": 1},
 "time": $UNIXTIME,
 "ver": "1.0"}
 ```

Instead of changing the setpoint (`"sp": $TEMP`) this can be used to change
the mode with `"md": 1` to turn off and `"md": 3` to turn on. These appear
to correspond to the `TstatMode` values seen in the `/devices/state` API.

## Delete schedule

Sent by app to `/v1/dev/$DID/in` with QOS=0:

```json
{"ver": "1.0", "id": $UNIXTIME,
 "src": {"type": 302, "ref": ""},
 "dest": {"type": 1, "ref": "$DID"},
 "msg": 34, "time": $UNIXTIME,
 "body": {"ver": "3.0.0", "hash": "", "events": [], "totalEvents": 0}}
}
```

And also this version:

```json
{"ver": "1.0", "id": $UNIXTIME,
 "src": {"type": 302, "ref": "$DID"},
 "dest": {"type": 1, "ref": "$DID"},
 "msg": 34, "time": $UNIXTIME,
 "body": {"ver": "3.0.0", "hash": "ea85ca7", "events": [], "totalEvents": 0}}
```

## Set schedule

Sent by app to `/v1/dev/$DID/in` with QOS=0:

```json
{"ver": "1.0", "id": $UNIXTIME,
 "src": {"type": 302, "ref": "223a5fcc-1b43-435e-9f37-7f99353cc805"},   # What is this UUID?
 "dest": {"type": 1, "ref": "$DID"},
 "msg": 34, "time": $UNIXTIME,
 "body": {
   "ver": "3.0.0", "hash": "f07d791",
   "events": ["1|0|1980|3|18.5|%|%|%|%|%",   # 1980 minutes = 33 hours in the week = Monday 9 am ("3|18.5" = on to 18.5°C)
              "1|1|2400|1|%|%|%|%|%|%",      # 2400 minutes = Monday 4 pm ("1|%" = off)
              "1|2|3420|3|18.5|%|%|%|%|%",
              "1|3|3840|1|%|%|%|%|%|%",
              "1|4|4860|3|18.5|%|%|%|%|%",
              "1|5|5280|1|%|%|%|%|%|%",
              "1|6|6300|3|18.5|%|%|%|%|%",
              "1|7|6720|1|%|%|%|%|%|%",
              "1|8|7740|3|18.5|%|%|%|%|%",  # 7740 minutes = Friday 9 am ("3|18.5" = on to 18.5°C)
              "1|9|8160|1|%|%|%|%|%|%"],    # 8160 minutes = Friday 4 pm ("1|%" = off)
   "totalEvents": 10, "createTime": 1737784923
}}
```

## Readings from device

Sent by device to `/v1/dev/$DID/batch` with QOS=0:

```json
{"ver": "1.0",
 "src": {"type": 1, "ref": "$DID"},
 "time": $UNIXTIME,
 "msg": 3,
 "id": ${large random number},     # 64-bits long?
 "body": {"readings": "$BASE64"}}
```

The "readings" are a binary data structure which contain raw (?) timestamped
data from the devices' sensors, typically at 30 second intervals, and sent
by the devices to the MQTT servers in batches covering 10-15 minutes typically.

There are multiple variants/versions of the data structures in the readings;
the first byte of each reading identifies its variant:

- Mysa V1 Baseboard devices (BB-V1-1) send v0 readings
- Mysa V1 Floor devices (INF-V1-0) send v1 readings.
- Mysa V2 Baseboard devices (BB-V2-0 and BB-V2-0-L "Lite") send v3 readings.

See the `parse_readings` function for the gory details of what is understood
so far, which is basically everything except for the final byte (which might
be some kind of checksum or CRC).

## Account management

All JSONful endpoints are on `https://app-prod.mysa.cloud`.

### Add new device to account

POST to `/devices` with body like:

```json
{
    "Id": "$DID",
    "TimeZone": "America/Chihuahua",
    "Name": "$NAME",
    "LastPaired": $UNIXTIME,
    "Home": "$HOME_UUID",
    "Model": "$MODEL",
    "schedGlobalOffset": 0
}
```

### Check updates

GET `/devices/update_available/$DID` resulting in a response like:

```json
{
    "update": false,
    "installedVersion": "3.16.2.3",
    "allowedVersion": "3.16.2.3"
}
```

or

```json
{
    "update": true,
    "installedVersion": "3.13.1.25",
    "allowedVersion": "3.16.2.3"
}
```

or, if the devices has never `POST`ed its firmware version to the appropriate endpoint, then after a few seconds' delay status 500 and:

```json
"Check update failed for $DID. Unable to determine neither installed version nor allowed version"
```

### Share device with another account

POST to `/users/$OTHER_USER_ID/updateUserDeviceAccess` with a body like:

```json
{
    "DeviceToRevoke": [
        "$DID"
    ],
    "DeviceToGrantAccess": [
        "$DID",
        "$DID",
        "$DID"
    ],
    "Home": "$HOME_UUID"
}
```

# Thermostats connect to...

- Same MQTT host on port 8883
- india.colorado.edu NTP
- devices10010.getmysa.com (sometimes?)
