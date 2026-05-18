#!/bin/bash
set -e -o pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 SSID PASSWORD" >&2
    exit 1
fi
SSID="$1"
PASSWORD="$2"
URL="http://192.168.4.1:57961"

echo "Checking for Mysa device in pairing mode at $URL ..."
curl -fsm3 "$URL/identify"

tf=$(mktemp wifi_config_XXXXX.json)
echo -e '{"ssid": "'"$SSID"'", "pass": "'"$PASSWORD"'"}' > "$tf"

pubkey=$(curl -fsm3 "$URL/pubkey")
echo "Got pubkey for Mysa device..."

echo "Sending WiFi network and password to Mysa device..."
md=$(openssl rsautl -encrypt -pubin -inkey /dev/stdin -in "$tf" -pkcs <<< "$pubkey"|base64 -w0)
curl -fsm30 "$URL/network/" -H "mysa-data: $md"

echo "Checking Mysa device WiFi connectivity..."
curl -fsm3 "$URL/connected"

echo "Rebooting Mysa device..."
curl -fsm3 "$URL/reboot"
