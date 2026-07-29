# Shared cold-water sensor

WH-station1 is the only owner of its MAX1238. The on-demand snapshot service
reads the complete Pi 1 sensor group and publishes versioned newline-delimited
JSON through a local Unix socket.

- WH-station1 water draws consume the complete snapshot locally.
- WH-station2 through WH-station4 retain their local hot, flow, and ambient
  readings and replace only the cold fields with the Pi 1 stream.
- Each recorded draw row identifies `cold_source_station` and
  `cold_source_timestamp_pacific`.

## Lifecycle

`cold-water.socket` remains active without opening hardware. The first local or
SSH-proxied client causes systemd to start `cold-water.service`. One acquisition
loop broadcasts each snapshot to all connected clients. Five seconds after the
last client disconnects, the service closes the ADC and exits.

## Pi 1 systemd setup

The unit files assume the repository is
`/home/pi/conformance_testing_team`, the hardware user is `pi`, and a restricted
SSH group named `coldwater` exists.

```bash
sudo install -m 0644 systemd/cold-water.socket /etc/systemd/system/
sudo install -m 0644 systemd/cold-water.service /etc/systemd/system/
sudo install -m 0755 systemd/cold-water-ssh-proxy.py /usr/local/bin/cold-water-ssh-proxy
sudo systemctl daemon-reload
sudo systemctl enable --now cold-water.socket
```

Only enable these units on WH-station1.

## Restricted SSH

Create one unique Ed25519 client key on each of WH-station2, WH-station3, and
WH-station4. Do not commit private keys or `authorized_keys`.

Each public key installed for the dedicated Pi 1 `coldwater` account must use a
forced command and restrictions similar to:

```text
restrict,command="/usr/local/bin/cold-water-ssh-proxy" ssh-ed25519 AAAA...
```

Pin WH-station1's host key on every client and retain
`StrictHostKeyChecking=yes`. The application also enables SSH keepalives and
does not permit password prompts. The proxy is root-owned, contains no station
credentials, provides no shell, and can access only the local snapshot socket
through membership in the `coldwater` group.

Client defaults may be overridden without changing the shared repository:

```text
COLD_WATER_PI1_HOST
COLD_WATER_SSH_USER
COLD_WATER_SSH_IDENTITY_FILE
```

The defaults are `WH-station1`, `coldwater`, and normal SSH key discovery.
Private keys and `known_hosts` remain in each Pi user's `.ssh` directory and
must never be stored in this repository.

School IT policy must permit SSH between the station devices. Do not bypass
network isolation or other institutional controls.

## Health behavior

The valve cannot open until the client receives a fresh snapshot. Clients
reject unsupported protocol versions, an unexpected source station,
non-advancing sequence numbers, sensor errors, stale timestamps, future clock
skew, and stream timeouts. Losing the stream during a draw raises an error and
the existing fail-safe cleanup closes the local valve.
