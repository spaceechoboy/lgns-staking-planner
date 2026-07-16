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
# Anubis 리베이스 인덱스 오라클 — currentIndex/currentEpoch/lastUpdateTime (틱=푸셔 0xFcd86F75)
ANU_ORACLE = "0xb4E5b7665186229d8A5B0ba3706c5C119dD1B47b"
O_INDEX = "0x26987b60"; O_EPOCH = "0x76671808"; O_LUT = "0xc8f33c91"
S_EPOCH = "0x900cf0cf"; S_CIRC = "0x9358928b"; S_TOTAL = "0x18160ddd"; S_INFO = "0x2e340599"
S_INDEX = "0x2986c0e5"; S_EXTRA = "0xb01d3563"; S_STAKES = "0x584b62a1"
SLOT_GI = "0x6b"; SLOT_EP = "0x6c"; SLOT_DEN = "0x71"   # Anubis globalIndex / epoch / denom (vault 확정)
# Polygon LONG 추가보상: globalIndex 0x6a · epoch 0x6b · 율 denom = 1e9 (slot 0x71의 2e10은 율 denom 아님)
# 에폭 12h(카운터 7일 2/day 확정), gi-delta = ref-스테이커와 2방식 일치 — vault [[polygon-extra-reward-rate]] 2026-06-19
POLY_SLOT_GI = "0x6a"; POLY_SLOT_EP = "0x6b"; POLY_EXTRA_DENOM = 10 ** 9
SEED = {"rebasePoly": 0.1496, "rebaseSched": 0.1375, "rebaseAnu": 0.1495,
        "poly360": 0.12, "poly600": 0.0703, "anu360": 0.15, "anu600": 0.195}
# 시드 = 2026-07-16 온체인 실측(오라클 틱 13개·gi 아카이브 델타). poly600은 0.0783→0.0703 하락 반영.
# Anubis 복리 리베이스 = 6h 에폭 · ~0.1495%/epoch — vault [[anubis-rebase-epoch-operator-schedule]]
# 추가보상은 별개 카운터(slot 0x6c) ~12h 에폭 (A360=0.15% A600=0.195%) — vault 추가보상 페이지
ANU_REBASE_EPOCH_H = 6   # 폴백 시드 전용. 실측 epochH는 오라클 lastUpdateTime 차로 계산.
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
def store_poly(addr, slot): return poly("eth_getStorageAt", [addr, slot, "latest"])
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

    # ── Polygon extra (globalIndex 0x6a / epoch 0x6b / denom 1e9, epoch-counter 델타 — ref-스테이커 불요) ──
    def poly_extra(ctr, seed_key, prev_node):
        # dep=0(같은 12h 에폭 내 재스냅샷)이면 직전 실측값 유지 — 시드로 리셋하지 않는다(2026-07-16 수정)
        base = prev_node.get("pctPerEpoch", SEED[seed_key]) if prev_node else SEED[seed_key]
        gi = store_poly(ctr, POLY_SLOT_GI); epc = store_poly(ctr, POLY_SLOT_EP)
        if not gi or not epc:
            return {"pctPerEpoch": base, "epochH": 12, "globalIndex": None, "epoch": None, "denom": str(POLY_EXTRA_DENOM)}
        gi_now = int(gi, 16); ep_now = int(epc, 16)
        node = {"pctPerEpoch": base, "epochH": 12, "globalIndex": str(gi_now), "epoch": ep_now, "denom": str(POLY_EXTRA_DENOM)}
        if prev_node and prev_node.get("globalIndex") and prev_node.get("epoch") is not None:
            dep = ep_now - int(prev_node["epoch"])
            if dep > 0:
                node["pctPerEpoch"] = clamp((gi_now - int(prev_node["globalIndex"])) / dep / POLY_EXTRA_DENOM * 100, base)
        return node

    out = {"schema": 1, "generated": gen,
           "poly": {"block": pblock,
                    "rebase": {"pctPerEpoch": rebasePoly, "sched": sched, "epochH": 6},
                    "extra": {"long360": poly_extra(LONG360, "poly360", pv.get("poly", {}).get("extra", {}).get("long360")),
                              "long600": poly_extra(LONG600, "poly600", pv.get("poly", {}).get("extra", {}).get("long600"))}},
           "anubis": {}}

    # ── Anubis rebase — 오라클 epoch-delta 실측 ──
    # 율 = (idx_now/idx_prev)^(1/Δepoch)−1, Δepoch=오라클 currentEpoch 카운터 차(정수).
    # epochH = Δ(lastUpdateTime)÷Δepoch (온체인 틱 타임스탬프 — realized).
    # ⚠ 구 방식(경과시간÷6h 가정)은 CI cron 지연 시 율을 왜곡(0.1135% 오표시, 2026-07-16 근본수정)
    #   — 런북 [[lgns-cadence-blocktime-bug-transfix]] 불변원칙: 시간÷가정에폭 금지.
    idx = call_anu(ANU_ORACLE, O_INDEX) or call_anu(ANU_SLGNS, S_INDEX)
    epch = call_anu(ANU_ORACLE, O_EPOCH)
    lut = call_anu(ANU_ORACLE, O_LUT)
    ablk = rpc(ANU_RPC, "eth_blockNumber", [])
    ablock = int(ablk, 16) if ablk else None
    pr = pv.get("anubis", {}).get("rebase", {})
    rebaseAnu = pr.get("pctPerEpoch", SEED["rebaseAnu"])
    epochH_anu = pr.get("epochH", ANU_REBASE_EPOCH_H)
    idx_now = int(idx, 16) / 1e9 if idx else None
    ep_now = int(epch, 16) if epch else None
    lut_now = int(lut, 16) if lut else None
    if idx_now and ep_now and pr.get("index") and pr.get("epoch"):
        dep = ep_now - int(pr["epoch"])
        if dep > 0 and idx_now > float(pr["index"]):
            rebaseAnu = clamp(((idx_now / float(pr["index"])) ** (1 / dep) - 1) * 100, rebaseAnu)
            if lut_now and pr.get("lut") and lut_now > int(pr["lut"]):
                epochH_anu = round((lut_now - int(pr["lut"])) / dep / 3600.0, 2)

    # ── Anubis extra (globalIndex 0x6b / epoch 0x6c / denom 0x71) ──
    def anu_extra(ctr, seed_key, prev_node):
        # dep=0이면 직전 실측값 유지 — 시드로 리셋하지 않는다(2026-07-16 수정)
        base = prev_node.get("pctPerEpoch", SEED[seed_key]) if prev_node else SEED[seed_key]
        gi = store_anu(ctr, SLOT_GI); epc = store_anu(ctr, SLOT_EP); den = store_anu(ctr, SLOT_DEN)
        if not gi or not epc:
            return {"pctPerEpoch": base, "epochH": 12, "globalIndex": None, "epoch": None, "denom": "1000000000"}
        gi_now = int(gi, 16); ep_now = int(epc, 16)
        denom = int(den, 16) if (den and int(den, 16) > 0) else 10 ** 9
        node = {"pctPerEpoch": base, "epochH": 12, "globalIndex": str(gi_now), "epoch": ep_now, "denom": str(denom)}
        if prev_node and prev_node.get("globalIndex") and prev_node.get("epoch") is not None:
            dep = ep_now - int(prev_node["epoch"])
            if dep > 0:
                node["pctPerEpoch"] = clamp((gi_now - int(prev_node["globalIndex"])) / dep / denom * 100, base)
        return node

    out["anubis"] = {"block": ablock,
                     "rebase": {"pctPerEpoch": rebaseAnu, "epochH": epochH_anu,
                                "index": (round(idx_now, 6) if idx_now else None),
                                "epoch": ep_now, "lut": lut_now},
                     "extra": {"long360": anu_extra(ANU_L360, "anu360", pv.get("anubis", {}).get("extra", {}).get("long360")),
                               "long600": anu_extra(ANU_L600, "anu600", pv.get("anubis", {}).get("extra", {}).get("long600"))}}

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("wrote", OUT)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
