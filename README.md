# Sentinel — AI Risk Responder on Reactive Network

**Track: Reactive Meets AI** · Reactive Omni Buildathon

Sentinel is a cross-chain risk-control loop with a **local LLM inside the reactive path**: an
oracle feed on Base Sepolia is watched by a reactive contract on Reactive Lasna, anomalies are
judged by an AI agent running on a self-hosted server, and the decision is committed back
on-chain before a callback executes the protective action on the destination chain.

Every step of the loop is a real, verifiable transaction.

## Architecture

```
 ┌───────────────────────┐        ┌────────────────────────────┐        ┌───────────────────────┐
 │  BASE SEPOLIA (84532) │        │  REACTIVE LASNA (5318007)  │        │  BASE SEPOLIA (84532) │
 │                       │        │                            │        │                       │
 │   MockOracle          │ event  │   SentinelReactive         │        │  SentinelDestination  │
 │   setPrice() ─────────┼──────► │   subscribe + EMA filter   │        │  AbstractCallback     │
 │   PriceUpdated        │        │   AnomalyDetected ─────────┼───┐    │                       │
 │                       │        │                            │   │    │                       │
 │                       │        │   submitDecision() ◄───────┼───┼────┤                       │
 │                       │        │        │ requestCallback   │   │    │                       │
 │                       │        │        ▼                  │   │    │                       │
 │                       │        │   SYSTEM 0x8888…8888 ─────┼───┼───►│ ◄── callback proxy    │
 │                       │        └────────────────────────────┘   │    │   executeDecision()   │
 │                       │                                         │    │   DecisionExecuted    │
 └───────────────────────┘        ┌────────────────────────────┐   │    └───────────────────────┘
                                  │  AI AGENT (off-chain VPS)  │   │
                                  │  listener ─► prompt ───────┼───┘
                                  │  local LLM (Ollama)        │
                                  │  decision JSON ─► commit   │
                                  └────────────────────────────┘
```

**Why this belongs in "Reactive Meets AI":** the LLM is not bolted on the side. The reactive
contract performs an on-chain pre-filter (EMA baseline + deviation band) so the agent only wakes
for real anomalies; the agent's decision is **committed as a transaction** (`submitDecision`)
with a decision hash and the model's own latency; and the callback carries both to the
destination chain where the action executes. Kill the agent and the on-chain sentinel keeps
detecting; kill the oracle and the agent has nothing to judge — the loop is genuinely
AI-in-the-middle, with an audit trail for every hop.

## Deployed contracts (testnet)

| Contract | Chain | Address |
|---|---|---|
| `MockOracle` | Base Sepolia (84532) | `0x6cb2896ea1a58277F4F62b5c7F4d54235f25BA42` |
| `SentinelReactive` | Reactive Lasna (5318007) | `0x6cb2896ea1a58277F4F62b5c7F4d54235f25BA42` |
| `SentinelReactive` (v1, superseded) | Reactive Lasna | `0x557Fc1aF2CfA6fb40cC5B43fA5b8194E08DB158B` |
| `SentinelDestination` | Base Sepolia (84532) | `0x146602dE80026F4442DE45D30071227130a1da3f` |
| `SentinelDestination` (v1, superseded) | Base Sepolia | `0xB2A56CacE9ff77468400B081Ae8E7bB7e25B0aeb` |

All four are verified on Sourcify. The oracle and the reactive contract share an address across
chains because CREATE addresses are deterministic per (deployer, nonce) — they are different
contracts on different chains.

## Verified end-to-end run

The demo scenario: the oracle price runs 2000 → 2010 → 1995, then crashes to 980 while the EMA
baseline sits at 1247 (deviation 2141 bps, far beyond the 1200 bps band).

| Step | Chain | Evidence |
|---|---|---|
| 1. Oracle emits crash price | Base Sepolia | `setPrice(980)` tx, event `PriceUpdated` |
| 2. RC reacts + pre-filter trips | Lasna | `AnomalyDetected(eventId=3, price=980, ema=1247, dev=2141bps)` |
| 3. Agent decides | off-chain | Ollama `qwen2.5:0.5b` → `{"action":"ALERT","confidence":100}` in **1963 ms** |
| 4. Decision committed | Lasna | `submitDecision` tx `0xcc3ffe646c618a61c0d6ead8a4adefcfc7ae8a6577fb18077ac413aa64c7d65e` |
| 5. Callback executes | Base Sepolia | tx `0x968acf380d9578c3ff4695f7b40d13c93fadceef57b438b3b0cbe9f3baf6d136` |

Post-execution destination state: `exposureBps 10000 → 5000` (ALERT halves exposure),
`decisionsExecuted = 1`, and the `DecisionExecuted` event carries the decision hash and the
model latency (1963 ms) — the AI's timing is auditable on-chain. Decided-at → executed-at
spans 2 seconds of block time.

Earlier decisions in the same session: anomaly #1 (1231 bps) → REDUCE, committed in tx
`0xda6b39c7142552444fb62dfb2aed88a34f5353aff7c516dfdbfdcd84ddc329f2`; anomaly #2 (1743 bps) →
HOLD. All three decisions are visible on the destination/RC event history.

## The agent

`agent/sentinel_agent.py` — zero third-party dependencies (urllib + json + `cast`):

1. Polls `eth_getLogs` on Lasna for `AnomalyDetected` events (topic0 computed via `cast sig-event`).
2. Builds a compact market-context prompt: anomaly report + recent price ring buffer read from the RC.
3. Queries a **local Ollama** OpenAI-compatible endpoint; reasoning-model replies are handled
   (chain-of-thought in `reasoning`, JSON extraction with a keyword-scan fallback).
4. Commits the decision via `submitDecision(eventId, action, decisionHash, modelLatencyMs)` —
   `decisionHash` is a deterministic keccak over the event + decision so any observer can verify
   what the model decided.
5. Records event-block-time vs decision time for latency measurement.

```bash
export REACTIVE_RPC=https://lasna-rpc.rnk.dev/
export RC_ADDRESS=0x6cb2896ea1a58277F4F62b5c7F4d54235f25BA42
export PRIVATE_KEY=0x…            # agent EOA (testnet burner)

python3 agent/sentinel_agent.py --dry-run $RC_ADDRESS   # decide, don't submit
python3 agent/sentinel_agent.py $RC_ADDRESS             # one pass
python3 agent/sentinel_agent.py --loop $RC_ADDRESS      # watch continuously
```

## Contract design notes

- **On-chain pre-filter.** `SentinelReactive` keeps an EMA (α = 0.3) of observed prices in a
  16-slot ring buffer and only emits `AnomalyDetected` when deviation breaches the band. The
  LLM never sees routine ticks — the reactive network pays for `react()` per event, so the
  filter is an economic control as much as a signal-quality one.
- **Replay-safe decisions.** `submitDecision` rejects unknown events and duplicates, so the
  agent can be restarted at any time without double-executing actions.
- **Audit trail.** `DecisionExecuted` carries `decisionHash` + `modelLatencyMs` + `exposureAfter`,
  binding the off-chain model run to its on-chain consequence.
- **Actions.** `HOLD` (no change), `REDUCE` (halve exposure), `ALERT` (cut exposure to floor and
  flag). The destination simulates a treasury; swapping in a real DeFi position manager is a
  one-contract change since the payload is a plain ABI call.

## Lessons from building on Reactive Omni

- `LogRecord.opCode` is the **number of topics** of the original log (LOG2 → 2), not an enum —
  a wrong guard silently drops every event while `react()` still burns lREACT.
- `data` holds only the non-indexed parameters; indexed ones live in `topics`.
- The destination's `callbackSender` must equal the **actual requesting RC address**. A stale
  sender after redeploying the RC makes every callback revert, surfacing only as a
  `CallbackFailure` event from the destination proxy — nothing appears in `getCallbacks`.
- Callbacks are billed to the **recipient** in the destination chain's native token; a failed
  callback is billed too. Any debt > 0 blocks delivery silently.
- The callback payload's first argument is a placeholder the network overwrites with the
  requesting RC's address — reserve it and auth with `onlyCallbackSender`.
- Reactive-chain gas is ~100+ gwei; keep deploy headroom (`balance ≥ value + ~0.6 lREACT`).
- Deterministic CREATE: the same (deployer, nonce) yields the same address on every chain.

## Repo layout

```
src/MockOracle.sol          origin price feed (Base Sepolia)
src/SentinelReactive.sol    reactive contract: subscribe, EMA pre-filter, decisions, callbacks
src/SentinelDestination.sol destination: executes actions, on-chain audit trail
agent/sentinel_agent.py     AI agent: listener → local LLM → on-chain commit
deployments.json            deployed addresses
```

## Build & deploy

```bash
forge build
forge create --broadcast --rpc-url https://sepolia.base.org \
  --private-key $KEY src/MockOracle.sol:MockOracle
forge create --broadcast --rpc-url https://lasna-rpc.rnk.dev/ \
  --private-key $KEY --value 0.5ether src/SentinelReactive.sol:SentinelReactive \
  --constructor-args 84532 <ORACLE_ADDR>
forge create --broadcast --rpc-url https://sepolia.base.org \
  --private-key $KEY src/SentinelDestination.sol:SentinelDestination \
  --constructor-args 0x476F44b11F5C942c58f4c8E3d0300E5710743585 <RC_ADDR>
cast send <RC_ADDR> "setRecipient(uint256,address)" 84532 <DEST_ADDR> --rpc-url https://lasna-rpc.rnk.dev/
```

## Demo video

See the submission on DoraHacks (linked from the build page) — the video walks the live loop:
oracle crash → reactive detection → local LLM decision → on-chain commit → callback execution,
with every transaction hash shown on its explorer.

## License

MIT
