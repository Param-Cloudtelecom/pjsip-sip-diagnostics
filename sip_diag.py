#!/usr/bin/env python3
"""
sip_diag.py - pjsip-based SIP registration & call diagnostic client.

Built for the same job packet-level tools (Wireshark/tshark/sngrep/Homer)
do for live troubleshooting, but as a scriptable client: register against a
target (an SBC, a trunk, a Cloud PBX extension), place a test call, and
report hard numbers - registration latency, call setup time, and RTP
stream quality (jitter, packet loss) - so a SIP trunk or NAT traversal
problem can be reproduced and measured on demand instead of waiting for a
customer complaint and reconstructing it after the fact.

Requires: pjsua2 (PJSIP's Python bindings)
  pip install pjsua2
  (or build from source: https://docs.pjsip.org/en/latest/get-started/index.html)

Usage:
    python sip_diag.py --domain sbc.example.com --user 1000 --password secret \
                        --call-to 1001 --duration 5
"""
import argparse
import sys
import time

try:
    import pjsua2 as pj
except ImportError:
    print("pjsua2 not installed. See README.md for build/install instructions.", file=sys.stderr)
    sys.exit(1)


class DiagAccountCallback(pj.AccountCallback):
    def __init__(self, account):
        pj.AccountCallback.__init__(self, account)
        self.registered = False
        self.register_started_at = None

    def on_reg_state(self):
        info = self.account.getInfo()
        elapsed = (time.time() - self.register_started_at) if self.register_started_at else None
        print(f"[REGISTER] status={info.regStatus} text={info.regStatusText} "
              f"latency={elapsed:.3f}s" if elapsed else f"[REGISTER] status={info.regStatus}")
        self.registered = info.regIsActive


class DiagCall(pj.Call):
    def __init__(self, account, call_id=pj.PJSUA_INVALID_ID):
        pj.Call.__init__(self, account, call_id)
        self.invite_sent_at = None
        self.answered_at = None
        self.media_active = False

    def onCallState(self):
        ci = self.getInfo()
        print(f"[CALL] state={ci.stateText} last_status={ci.lastStatusCode}")

        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED and self.answered_at is None:
            self.answered_at = time.time()
            setup_time = self.answered_at - self.invite_sent_at
            print(f"[CALL] setup time (INVITE -> 200 OK): {setup_time:.3f}s")

        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            print(f"[CALL] ended, cause={ci.lastReason}")

    def onCallMediaState(self):
        ci = self.getInfo()
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                self.media_active = True
                aud_med = self.getAudioMedia(mi.index)
                stat = aud_med.getStreamStat() if hasattr(aud_med, "getStreamStat") else None
                print("[MEDIA] audio stream active")
                if stat:
                    self._print_stream_stats(stat)

    def _print_stream_stats(self, stat):
        rx = stat.rxStat
        tx = stat.txStat
        print(f"[RTP RX] pkt={rx.pkt} loss={rx.loss} jitter_avg={rx.jitterUsec.avg / 1000:.2f}ms "
              f"discard={rx.discard}")
        print(f"[RTP TX] pkt={tx.pkt} loss={tx.loss} jitter_avg={tx.jitterUsec.avg / 1000:.2f}ms")


def run_diagnostic(domain, user, password, call_to, duration, transport):
    ep_cfg = pj.EpConfig()
    ep_cfg.logConfig.level = 3
    ep = pj.Endpoint()
    ep.libCreate()
    ep.libInit(ep_cfg)

    if transport == "tls":
        tcfg = pj.TransportConfig()
        tcfg.port = 0
        ep.transportCreate(pj.PJSIP_TRANSPORT_TLS, tcfg)
    else:
        tcfg = pj.TransportConfig()
        tcfg.port = 0
        ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

    ep.libStart()

    acc_cfg = pj.AccountConfig()
    acc_cfg.idUri = f"sip:{user}@{domain}"
    acc_cfg.regConfig.registrarUri = f"sip:{domain}"
    cred = pj.AuthCredInfo("digest", "*", user, 0, password)
    acc_cfg.sipConfig.authCreds.append(cred)

    account = pj.Account()
    cb = DiagAccountCallback(account)
    account.create(acc_cfg, cb=cb)
    cb.register_started_at = time.time()

    print(f"Registering {user}@{domain} ...")
    timeout = time.time() + 10
    while not cb.registered and time.time() < timeout:
        ep.libHandleEvents(200)

    if not cb.registered:
        print("Registration failed or timed out.", file=sys.stderr)
        ep.libDestroy()
        sys.exit(2)

    if call_to:
        call = DiagCall(account)
        call.invite_sent_at = time.time()
        call_param = pj.CallOpParam(True)
        print(f"Placing test call to {call_to} ...")
        call.makeCall(f"sip:{call_to}@{domain}", call_param)

        end_at = time.time() + duration
        while time.time() < end_at:
            ep.libHandleEvents(200)

        hangup_param = pj.CallOpParam(True)
        try:
            call.hangup(hangup_param)
        except Exception:
            pass
        ep.libHandleEvents(500)

    account.shutdown()
    ep.libDestroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="SIP domain / SBC / trunk host")
    parser.add_argument("--user", required=True, help="SIP username/extension")
    parser.add_argument("--password", required=True, help="SIP auth password")
    parser.add_argument("--call-to", help="Number/extension to test-call after registering")
    parser.add_argument("--duration", type=int, default=5, help="Seconds to hold the test call")
    parser.add_argument("--transport", choices=["udp", "tls"], default="udp")
    args = parser.parse_args()

    run_diagnostic(args.domain, args.user, args.password, args.call_to, args.duration, args.transport)


if __name__ == "__main__":
    main()
