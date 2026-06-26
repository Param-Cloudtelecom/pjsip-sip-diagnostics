# pjsip-sip-diagnostics

A scriptable SIP registration/call diagnostic client built on **pjsua2**
(PJSIP's Python bindings). It does the same job Wireshark, `tshark`,
`sngrep`, and Homer (HEP) do for *passive* call-flow visibility — except
this one actively reproduces the problem on demand: register, place a test
call, and report hard numbers instead of waiting for a customer to call in
with "the audio was choppy."

## What it measures

- **Registration latency** — time from sending REGISTER to a confirmed
  200 OK, useful for catching slow/flaky registrar responses before
  endpoints start timing out and re-registering in a loop.
- **Call setup time** — INVITE → 200 OK timing, the first thing to check
  when a customer reports "calls take forever to connect."
- **RTP stream quality** — packet count, packet loss, jitter (ms), and
  discards for both RX and TX, pulled directly from pjsua2's stream
  statistics once media is active.

## Why this approach

Most SIP debugging starts reactively — something breaks, then you reach
for Wireshark/sngrep to capture and reconstruct what happened. This tool
flips that: point it at an SBC, trunk, or extension and it **proactively**
exercises the exact signaling + media path, on a schedule or on demand,
so regressions in NAT traversal, TLS/SRTP negotiation, or trunk health
show up as numbers in a log before a customer notices.

Pairs naturally with [`kamailio-sbc-router`](https://github.com/Param-Cloudtelecom/kamailio-sbc-router)
and [`freeswitch-cloud-pbx`](https://github.com/Param-Cloudtelecom/freeswitch-cloud-pbx) —
run this against either to validate a config change actually fixed the
registration/NAT/RTP issue it was meant to fix, instead of guessing from a
single manual test call.

## Install

```bash
# pjsua2 is PJSIP's Python binding - build from source for a version that
# matches your installed PJSIP, or use a prebuilt wheel if available:
pip install pjsua2

# If building from source instead:
#   https://docs.pjsip.org/en/latest/get-started/index.html
#   ./configure && make dep && make && cd pjsip-apps/src/swig/python && make
```

## Usage

```bash
# Just verify registration against an SBC/trunk
python sip_diag.py --domain sbc.example.com --user 1000 --password secret

# Register and place a 5-second test call to extension 1001, with full
# RTP quality reporting
python sip_diag.py --domain sbc.example.com --user 1000 --password secret \
                    --call-to 1001 --duration 5

# Force TLS transport (test SRTP/TLS-terminated trunks specifically)
python sip_diag.py --domain sbc.example.com --user 1000 --password secret \
                    --call-to 1001 --transport tls
```

Example output:

```
Registering 1000@sbc.example.com ...
[REGISTER] status=200 text=OK latency=0.084s
Placing test call to 1001 ...
[CALL] state=CALLING last_status=100
[CALL] state=CONNECTING last_status=180
[CALL] state=CONFIRMED last_status=200
[CALL] setup time (INVITE -> 200 OK): 0.341s
[MEDIA] audio stream active
[RTP RX] pkt=240 loss=0 jitter_avg=4.20ms discard=0
[RTP TX] pkt=238 loss=0 jitter_avg=0.00ms
[CALL] state=DISCONNECTED last_status=200
[CALL] ended, cause=Normal call clearing
```

## Where I'd take this next

- Push the per-run stats into the same `cdr`-style Postgres table used in
  [`freeswitch-cloud-pbx`](https://github.com/Param-Cloudtelecom/freeswitch-cloud-pbx),
  so synthetic test-call quality is trended on the same dashboard as real
  traffic
- Wrap it in a cron/systemd timer for scheduled synthetic monitoring against
  each tenant's trunk, alerting if jitter/loss crosses a threshold
- Add a `--pcap` flag to capture the actual exchange alongside the summary
  stats, for when a number alone isn't enough to diagnose the root cause
