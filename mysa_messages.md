# Mysa MQTT messages

- `DID` is the 12-digit MAC address of the device.
- MQTT topics are `/v1/dev/$DID/{out,in}`
- `UNIXTIME` is in seconds, `UNIXTIMEMS` is in milliseconds
- `USER_UUID` is the UUID associated with a user account (seen in `/users` response

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
 "Current": 0.0,              # This seems to be "the current right now" as opposed to "the highest current seen" reported in /devices/state
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
{"body": {"ambTemp": 16.7, "dtyCycle": 1.0, "hum": 48.0, "stpt": 17.8},
 "id": ${large random number},     # 64-bits long?
 "msg": 40,
 "src": {"ref": "$DID", "type": 1},
 "time": $UNIXTIME,
 "ver": "1.0"}
```

The `Duty` value in `/devices/state` is very laggy compared to the `dtyCycle` seen here.

## "Check your settings"

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

## Firmware report?

Sent by devices to `/v1/dev/$DID/out` with QOS=0. Unsure what triggers it:

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
 "body": {"cmd": [{"sp": 17, "tm": -1}], "type": $TYPE, "ver": 1},
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
          "trig_src": 3,
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
