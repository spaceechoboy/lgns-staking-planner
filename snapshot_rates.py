#!/usr/bin/env python3
# LGNS Staking Planner — rates snapshot (READ-ONLY: eth_call/eth_getStorageAt만, 키·tx 없음)
# 직전 rates.json과 누적기 델타로 6개 보상률(%/epoch)을 산출. 없으면 seed. 폭증/음수는 seed/직전 유지.
import json, os, time, urllib.request

POLY_RPCS = ["https://polygon-rpc.com", "https://polygon.drpc.org",
             "https://polygon-bor-rpc.publicnode.com", "https://polygon.llamarpc.com", "https://1rpc.io/matic"]
ANU_RPC = "https://rpc.anubispace.org"
STAKING = "0x1964Ca90474b11FFD08af387b110ba6C96251Bfc"
SLGNS = "0x99a57E6C8558BC6689f894e068733ADf83C19725"
DISTRIB = "0x8DEa9182ca68E101C4B351E4601f56044a5Dd611"
LONG360 = "0x6652d0f0D7aEc5070804E55b7023d32B9Bbc4190"
LONG600 = "0x8cA97F41d2C81AF050656e8AD0Cf543820a24504"
REF360 = "0xFB69AAa41bC497D674cF42a1EdA2FF11465872dd"
REF600 = "0xedeC9331852eeB076811Ef8Bc60bceE10c74e352"
ANU_SLGNS = "0x2243aE29F73137d678197b61B0621AE942845B8C"
ANU_L360 = "0x88ea98af226Cd4402A3873400308a4D78784eCE6"
ANU_L600 = "0x04eD22c6d1D020A9B5e032E93D79ab28293EF72f"
S_EPOCH = "0x900cf0cf"; S_CIRC = "0x9358928b"; S_TOTAL = "0x18160ddd"; S_INFO = "0x2e340599"
S_INDEX = "0x2986c0e5"; S_EXTRA = "0xb01d3563"; S_STAKES = "0x584b62a1"
SLOT_GI = "0x6b"; SLOT_EP = "0x6c"; SLOT_DEN = "0x71"   # Anubis globalIndex / epoch / denom (vault 확정)
SEED = {"rebasePoly": 0.1487, "rebaseSched": 0.1397, "rebaseAnu": 0.15,
        "poly360": 0.12, "poly600": 0.0783, "anu360": 0.15, "anu600": 0.195}
# Anubis 복리 리베이스 = 6h 에폭 · 0.15%/epoch (APY ~778%) — vault [[anubis-rebase-epoch-operator-schedule]]
# 추가보상은 별개 카운터(slot 0x6c) ~12h 에폭 (360=0.15% 600=0.195%) — vault 추가보상 페이지
ANU_REBASE_EPOCH_H = 6
MIN_DEPS = 0.3   # 시간기반 델타 최소 표본간격(에폭). 너무 가까운 두 스냅샷은 불신 → seed 유지
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "rates.json")


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.load(r).get("result")
        return res if (res and res != "0x") else None


def poly(method, params):
    for u in POLY_RPCS:
        try:
            v = rpc(u, method, params)
            if v is not None:
                return v
        except Exception:
            pass
    return None


def call_poly(to, data): return poly("eth_call", [{"to": to, "data": data}, "latest"])
def call_anu(to, data): return rpc(ANU_RPC, "eth_call", [{"to": to, "data": data}, "latest"])
def store_anu(addr, slot): return rpc(ANU_RPC, "eth_getStorageAt", [addr, slot, "latest"])
def addr32(a): return a.lower().replace("0x", "").rjust(64, "0")
def idx32(i): return format(i, "x").rjust(64, "0")


def word(hex_, i):
    h = hex_[2:] if hex_.startswith("0x") else hex_
    return int(h[i * 64:i * 64 + 64] or "0", 16)


def load_prev():
    try:
        with open(OUT) as f:
            return json.load(f)
    except Exception:
        return None


def epochs_between(prev_iso, now_ts, epochH):
    if not prev_iso:
        return None
    try:
        prev = time.mktime(time.strptime(prev_iso, "%Y-%m-%dT%H:%M:%SZ"))
        dh = (now_ts - prev) / 3600.0
        return dh / epochH if epochH > 0 else None
    except Exception:
        return None


def clamp(pct, fallback):
    if pct is None or pct <= 0 or pct > 2.0:
        return round(fallback, 4)
    return round(pct, 4)


def main():
    prev = load_prev()
    now = time.time()
    gen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    pv = prev or {}

    # ── Polygon rebase (instant) ──
    ep = call_poly(STAKING, S_EPOCH)
    circ = call_poly(SLGNS, S_CIRC) or call_poly(SLGNS, S_TOTAL)
    rblk = poly("eth_blockNumber", [])
    pblock = int(rblk, 16) if rblk else None
    rebasePoly = SEED["rebasePoly"]
    if ep and circ:
        dist = word(ep, 3); c = int(circ, 16)
        if c > 0:
            rebasePoly = clamp(dist / c * 100, SEED["rebasePoly"])
    info1 = call_poly(DISTRIB, S_INFO + idx32(1))
    sched = round(word(info1, 0) / 1e6 * 100, 4) if info1 else SEED["rebaseSched"]

    # ── Polygon extra (extraInterest(ref,0) ÷ 원금, epoch-time 델타) ──
    def poly_extra(ctr, ref, seed_key, prev_node):
        accum = call_poly(ctr, S_EXTRA + addr32(ref) + idx32(0))
        stk = call_poly(ctr, S_STAKES + addr32(ref) + idx32(0))
        if not accum or not stk:
            return {"pctPerEpoch": SEED[seed_key], "epochH": 12, "accum": None, "principal": None}
        accum_now = word(accum, 0); principal = word(stk, 0) / 1e9
        node = {"pctPerEpoch": SEED[seed_key], "epochH": 12, "accum": str(accum_now), "principal": round(principal, 4)}
        if prev_node and prev_node.get("accum") and principal > 0:
            deps = epochs_between(pv.get("generated"), now, 12)
            if deps and deps >= MIN_DEPS:
                ratio = (accum_now - int(prev_node["accum"])) / (principal * 1e9)
                node["pctPerEpoch"] = clamp(ratio / deps * 100, prev_node.get("pctPerEpoch", SEED[seed_key]))
        return node

    out = {"schema": 1, "generated": gen,
           "poly": {"block": pblock,
                    "rebase": {"pctPerEpoch": rebasePoly, "sched": sched, "epochH": 6},
                    "extra": {"long360": poly_extra(LONG360, REF360, "poly360", pv.get("poly", {}).get("extra", {}).get("long360")),
                              "long600": poly_extra(LONG600, REF600, "poly600", pv.get("poly", {}).get("extra", {}).get("long600"))}},
           "anubis": {}}

    # ── Anubis rebase (index-delta) ──
    idx = call_anu(ANU_SLGNS, S_INDEX)
    ablk = rpc(ANU_RPC, "eth_blockNumber", [])
    ablock = int(ablk, 16) if ablk else None
    rebaseAnu = SEED["rebaseAnu"]; idx_now = None
    if idx:
        idx_now = int(idx, 16) / 1e9
        pidx = pv.get("anubis", {}).get("rebase", {}).get("index")
        if pidx:
            deps = epochs_between(pv.get("generated"), now, ANU_REBASE_EPOCH_H)
            if deps and deps >= MIN_DEPS and idx_now > float(pidx):
                rebaseAnu = clamp(((idx_now / float(pidx)) ** (1 / deps) - 1) * 100,
                                  pv.get("anubis", {}).get("rebase", {}).get("pctPerEpoch", SEED["rebaseAnu"]))

    # ── Anubis extra (globalIndex 0x6b / epoch 0x6c / denom 0x71) ──
    def anu_extra(ctr, seed_key, prev_node):
        gi = store_anu(ctr, SLOT_GI); epc = store_anu(ctr, SLOT_EP); den = store_anu(ctr, SLOT_DEN)
        if not gi or not epc:
            return {"pctPerEpoch": SEED[seed_key], "epochH": 12, "globalIndex": None, "epoch": None, "denom": "1000000000"}
        gi_now = int(gi, 16); ep_now = int(epc, 16)
        denom = int(den, 16) if (den and int(den, 16) > 0) else 10 ** 9
        node = {"pctPerEpoch": SEED[seed_key], "epochH": 12, "globalIndex": str(gi_now), "epoch": ep_now, "denom": str(denom)}
        if prev_node and prev_node.get("globalIndex") and prev_node.get("epoch") is not None:
            dep = ep_now - int(prev_node["epoch"])
            if dep > 0:
                node["pctPerEpoch"] = clamp((gi_now - int(prev_node["globalIndex"])) / dep / denom * 100,
                                            prev_node.get("pctPerEpoch", SEED[seed_key]))
        return node

    out["anubis"] = {"block": ablock,
                     "rebase": {"pctPerEpoch": rebaseAnu, "epochH": ANU_REBASE_EPOCH_H, "index": (round(idx_now, 6) if idx_now else None)},
                     "extra": {"long360": anu_extra(ANU_L360, "anu360", pv.get("anubis", {}).get("extra", {}).get("long360")),
                               "long600": anu_extra(ANU_L600, "anu600", pv.get("anubis", {}).get("extra", {}).get("long600"))}}

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("wrote", OUT)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
