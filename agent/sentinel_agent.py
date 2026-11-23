#!/usr/bin/env python3
"""Sentinel AI agent — the neural network inside the reactive loop.

Listens for AnomalyDetected events from SentinelReactive on Reactive Lasna,
builds a market-context prompt from the on-chain price history, asks a local
LLM (Ollama, OpenAI-compatible endpoint) for a risk decision, and commits the
decision back on-chain via submitDecision(). The reactive contract then fires
the callback that executes the action on the destination chain.

Zero third-party dependencies: urllib + json + subprocess(cast).

Usage:
    python3 agent.py                     # one poll cycle, then exit
    python3 agent.py --loop              # run forever, poll every 5 s
    python3 agent.py --dry-run           # decide, don't submit tx
Env:
    REACTIVE_RPC      (default https://lasna-rpc.rnk.dev/)
    RC_ADDRESS        SentinelReactive address
    PRIVATE_KEY       agent EOA key (omit for --dry-run)
    LLM_BASE          (default http://127.0.0.1:11434/v1)
    LLM_MODEL         (default qwen2.5:0.5b)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

RPC = os.environ.get("REACTIVE_RPC", "https://lasna-rpc.rnk.dev/")
LLM_BASE = os.environ.get("LLM_BASE", "http://127.0.0.1:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:0.5b")

ACTIONS = {0: "HOLD", 1: "REDUCE", 2: "ALERT"}

SYSTEM_PROMPT = (
    "You are Sentinel, a risk-control model for a crypto treasury. "
    "You receive a price anomaly report from an on-chain sentinel: the "
    "observed price, the EMA baseline, and the deviation in basis points. "
    "Recent price history is given oldest-first. Respond ONLY with compact "
    "JSON: {\"action\": \"HOLD\"|\"REDUCE\"|\"ALERT\", \"confidence\": 0-100, "
    "\"reason\": \"<max 12 words>\"}. "
    "Rules: deviation >= 1000 bps or a sharp reversal after a run-down "
    "warrants REDUCE; deviation >= 2500 bps or capitulation-style drop "
    "warrants ALERT; small noise is HOLD. Protect capital first."
)


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(RPC, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def latest_block():
    return int(rpc("eth_blockNumber", []), 16)


def get_block_ts(block_hex):
    return int(rpc("eth_getBlockByNumber", [block_hex, False])["timestamp"], 16)


def topic0():
    """Compute the AnomalyDetected topic0 with cast (keccak via solidity)."""
    out = subprocess.run(
        ["cast", "sig-event",
         "AnomalyDetected(uint256,uint256,uint256,uint256,uint256)"],
        capture_output=True, text=True, timeout=15)
    return out.stdout.strip()


def fetch_anomalies(rc_address, from_block):
    topic = topic0()
    logs = rpc("eth_getLogs", [{
        "address": rc_address,
        "topics": [topic],
        "fromBlock": hex(from_block),
        "toBlock": "latest",
    }])
    anomalies = []
    for lg in logs:
        data = lg["data"][2:]
        # uint256 price, ema, deviationBps, originBlock
        words = [int(data[i * 64:(i + 1) * 64], 16) for i in range(4)]
        anomalies.append({
            "eventId": int(lg["topics"][1], 16),
            "price": words[0],
            "ema": words[1],
            "deviationBps": words[2],
            "originBlock": words[3],
            "reactiveBlock": int(lg["blockNumber"], 16),
            "reactiveBlockTime": get_block_ts(lg["blockNumber"]),
            "txHash": lg["transactionHash"],
        })
    return anomalies


def fetch_recent_prices(rc_address):
    out = subprocess.run(
        ["cast", "call", rc_address,
         "getRecentPrices()(uint256[])", "--rpc-url", RPC],
        capture_output=True, text=True, timeout=20)
    raw = out.stdout.strip()
    if not raw.startswith("["):
        return []
    return [int(x.strip()) for x in raw.strip("[]").split(",") if x.strip()]


def decide(anomaly, recent):
    history = ", ".join(str(p) for p in recent) or "n/a"
    user = (
        f"Anomaly #{anomaly['eventId']}: price {anomaly['price']}, "
        f"EMA {anomaly['ema']}, deviation {anomaly['deviationBps']} bps. "
        f"Recent prices (oldest-first): {history}."
    )
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": 600,
    }).encode()
    req = urllib.request.Request(
        LLM_BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    latency_ms = int((time.time() - t0) * 1000)
    msg = resp["choices"][0]["message"]
    # reasoning models put the chain-of-thought in `reasoning`; combine both
    text = (msg.get("content") or "").strip()
    if not text:
        text = (msg.get("reasoning") or "").strip()
    # extract JSON object from the reply; fall back to keyword scan
    decision = None
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            decision = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            decision = None
    if decision is None:
        upper = text.upper()
        for kw in ("ALERT", "REDUCE", "HOLD"):
            if kw in upper:
                decision = {"action": kw, "confidence": 40,
                            "reason": "keyword fallback"}
                break
        if decision is None:
            decision = {"action": "HOLD", "confidence": 0,
                        "reason": "unparseable model output"}
    action = {"HOLD": 0, "REDUCE": 1, "ALERT": 2}.get(
        str(decision.get("action", "")).upper(), 0)
    try:
        conf = max(0, min(100, int(decision.get("confidence", 50))))
    except (TypeError, ValueError):
        conf = 50
    return {
        "action": action,
        "confidence": conf,
        "reason": str(decision.get("reason", ""))[:80],
        "raw": text[-200:],
        "latency_ms": latency_ms,
    }


def decision_hash(anomaly, decision):
    preimage = json.dumps({
        "eventId": anomaly["eventId"],
        "action": decision["action"],
        "price": anomaly["price"],
        "reason": decision["reason"],
    }, sort_keys=True)
    return "0x" + hashlib.sha3_256(preimage.encode()).hexdigest()


def submit(rc_address, anomaly, decision, private_key):
    dh = decision_hash(anomaly, decision)
    cmd = [
        "cast", "send", rc_address,
        "submitDecision(uint256,uint8,bytes32,uint64)",
        str(anomaly["eventId"]), str(decision["action"]), dh,
        str(min(decision["latency_ms"], 2**64 - 1)),
        "--rpc-url", RPC, "--private-key", private_key, "--json",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        receipt = json.loads(out.stdout)
        return receipt.get("transactionHash"), dh
    except json.JSONDecodeError:
        raise RuntimeError("cast send failed: " + out.stderr[:300])


def process(rc_address, state, dry_run, private_key):
    head = latest_block()
    frm = state["last_block"] + 1
    anomalies = fetch_anomalies(rc_address, frm)
    state["last_block"] = head
    for a in anomalies:
        if a["eventId"] in state["done"]:
            continue
        print(f"[agent] anomaly #{a['eventId']} price={a['price']} ema={a['ema']} dev={a['deviationBps']}bps")
        recent = fetch_recent_prices(rc_address)
        t_event = a["reactiveBlockTime"]
        d = decide(a, recent)
        print(f"[agent] decision: {ACTIONS[d['action']]} "
              f"conf={d['confidence']} model={d['latency_ms']}ms "
              f"reason=\"{d['reason']}\"")
        if dry_run:
            print("[agent] dry-run: not submitting")
        else:
            txh, dh = submit(rc_address, a, d, private_key)
            print(f"[agent] committed tx={txh} hash={dh[:10]}…")
        state["done"].add(a["eventId"])
        state["log"].append({
            "eventId": a["eventId"], "eventBlockTime": t_event,
            "decision": d, "decisionHash": decision_hash(a, d),
        })
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("rc_address", nargs="?",
                    default=os.environ.get("RC_ADDRESS", ""))
    args = ap.parse_args()
    if not args.rc_address:
        sys.exit("rc_address required (arg or RC_ADDRESS env)")
    pk = os.environ.get("PRIVATE_KEY", "")
    if not args.dry_run and not pk:
        sys.exit("PRIVATE_KEY required (or use --dry-run)")

    state = {"last_block": max(0, latest_block() - 5000), "done": set(), "log": []}
    print(f"[agent] watching {args.rc_address} on {RPC}")
    while True:
        try:
            state = process(args.rc_address, state, args.dry_run, pk)
        except Exception as e:
            print(f"[agent] cycle error: {e}")
        if not args.loop:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
