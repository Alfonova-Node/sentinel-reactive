// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { ISystemContract } from "@reactive/src/interfaces/ISystemContract.sol";
import { IReactive } from "@reactive/src/interfaces/IReactive.sol";
import { AbstractReactive } from "@reactive/src/base/AbstractReactive.sol";

/// @title SentinelReactive — AI-driven risk sentinel on Reactive Lasna.
/// @notice Subscribes to origin-chain oracle events, runs a deterministic
///         on-chain pre-filter (deviation from an EMA baseline), and flags
///         anomalies as events an off-chain AI agent listens to. The agent's
///         model decision is committed back through submitDecision(), which
///         triggers a callback that executes the protective action on the
///         destination chain. The AI is part of the running system: nothing
///         reaches the destination chain without a model decision.
contract SentinelReactive is AbstractReactive {
    // ------------------------------------------------------------------
    // Constants
    // ------------------------------------------------------------------

    /// @dev Keccak of PriceUpdated(address,uint256,uint256).
    uint256 public constant PRICE_TOPIC =
        uint256(keccak256(bytes("PriceUpdated(address,uint256,uint256)")));

    uint64 public constant CALLBACK_GAS_LIMIT = 300000;

    // Decision actions.
    uint8 public constant ACTION_HOLD = 0;
    uint8 public constant ACTION_REDUCE = 1;
    uint8 public constant ACTION_ALERT = 2;

    // ------------------------------------------------------------------
    // Origin configuration
    // ------------------------------------------------------------------

    uint256 public immutable ORIGIN_CHAIN_ID;
    address public immutable ORIGIN_CONTRACT;

    // ------------------------------------------------------------------
    // On-chain pre-filter state
    // ------------------------------------------------------------------

    /// @notice EMA of observed prices, scaled by 1e18. Warm-started at 1.
    uint256 public emaPrice = 1e18;
    /// @notice EMA warm-up flag: first observation seeds the EMA directly.
    bool public seeded;
    /// @notice EMA smoothing factor, scaled by 1e18 (0.5 = half-life of 1 event).
    uint256 public alpha = 5e17;
    /// @notice Deviation band, scaled by 1e18 (0.10 = flag at ±10% from EMA).
    uint256 public band = 1e17;
    /// @notice Last observed origin price.
    uint256 public lastPrice;
    uint256 public eventsSeen;
    uint256 public anomaliesDetected;

    // ------------------------------------------------------------------
    // AI decision state
    // ------------------------------------------------------------------

    address public agent;
    uint256 public callbackChainId;
    address public callbackRecipient;

    struct Decision {
        uint8 action;
        bytes32 decisionHash;
        uint64 modelLatencyMs;
        uint256 decidedAt;
        uint256 anomalyPrice;
    }

    mapping(uint256 => Decision) public decisions;
    uint256 public decisionsCommitted;

    // Ring buffer of recent origin prices for the agent's context window.
    uint256[16] public recentPrices;
    uint256 public cursor;

    // ------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------

    event AnomalyDetected(
        uint256 indexed eventId,
        uint256 price,
        uint256 ema,
        uint256 deviationBps,
        uint256 originBlock
    );
    event DecisionCommitted(
        uint256 indexed eventId,
        uint8 action,
        bytes32 decisionHash,
        uint64 modelLatencyMs,
        uint256 decidedAt
    );
    event CallbackDispatched(uint256 indexed eventId, uint8 action);

    // ------------------------------------------------------------------
    // Errors
    // ------------------------------------------------------------------

    error NotAgent();
    error NotOwner();
    error UnknownEvent();
    error DuplicateDecision();
    error RecipientNotSet();

    // ------------------------------------------------------------------
    // Modifiers
    // ------------------------------------------------------------------

    modifier onlyAgent() {
        if (msg.sender != agent) revert NotAgent();
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != agent) revert NotOwner(); // deployer == initial agent/owner
        _;
    }

    // ------------------------------------------------------------------
    // Construction
    // ------------------------------------------------------------------

    constructor(
        uint256 originChainId_,
        address originContract_
    ) payable {
        ORIGIN_CHAIN_ID = originChainId_;
        ORIGIN_CONTRACT = originContract_;
        agent = msg.sender;

        SYSTEM.subscribe(
            originChainId_,
            originContract_,
            PRICE_TOPIC,
            REACTIVE_IGNORE,
            REACTIVE_IGNORE,
            REACTIVE_IGNORE
        );
    }

    // ------------------------------------------------------------------
    // Reactive entry point
    // ------------------------------------------------------------------

    /// @inheritdoc IReactive
    function react(LogRecord memory log_) external onlySystem {
        if (log_.topic0 != PRICE_TOPIC || log_.opCode != 2) {
            return;
        }

        // topic1 = indexed token; data = (price, timestamp) non-indexed only.
        (uint256 price_, ) = abi.decode(log_.data, (uint256, uint256));
        lastPrice = price_;
        ++eventsSeen;
        recentPrices[cursor] = price_;
        cursor = (cursor + 1) % 16;

        if (!seeded) {
            emaPrice = price_;
            seeded = true;
            return;
        }

        // Exponential update of the baseline.
        emaPrice = (emaPrice * (1e18 - alpha) + price_ * alpha) / 1e18;

        // Deviation in basis points relative to the baseline.
        uint256 diff = price_ > emaPrice ? price_ - emaPrice : emaPrice - price_;
        uint256 deviationBps = (diff * 10000) / emaPrice;

        if (deviationBps >= (band * 10000) / 1e18) {
            ++anomaliesDetected;
            emit AnomalyDetected(
                anomaliesDetected,
                price_,
                emaPrice,
                deviationBps,
                log_.blockNumber
            );
        }
    }

    // ------------------------------------------------------------------
    // AI decision commitment (called by the off-chain agent EOA)
    // ------------------------------------------------------------------

    /// @notice Commit the model's decision for an anomaly and dispatch the
    ///         protective action to the destination chain via callback.
    function submitDecision(
        uint256 eventId_,
        uint8 action_,
        bytes32 decisionHash_,
        uint64 modelLatencyMs_
    ) external onlyAgent {
        if (callbackRecipient == address(0)) revert RecipientNotSet();
        if (eventId_ == 0 || eventId_ > anomaliesDetected) revert UnknownEvent();
        if (decisions[eventId_].decidedAt != 0) revert DuplicateDecision();

        decisions[eventId_] = Decision({
            action: action_,
            decisionHash: decisionHash_,
            modelLatencyMs: modelLatencyMs_,
            decidedAt: block.timestamp,
            anomalyPrice: lastPrice
        });
        ++decisionsCommitted;

        emit DecisionCommitted(eventId_, action_, decisionHash_, modelLatencyMs_, block.timestamp);

        bytes memory payload = abi.encodeWithSelector(
            ISentinelDestination.executeDecision.selector,
            address(0), // placeholder: overwritten with this contract's address
            eventId_,
            action_,
            decisionHash_,
            modelLatencyMs_,
            block.timestamp
        );

        SYSTEM.requestCallbackV_1_0(
            ISystemContract.CallbackConfiguration_V_1_0({
                chainId: callbackChainId,
                recipient: callbackRecipient,
                gasLimit: CALLBACK_GAS_LIMIT,
                payload: payload
            })
        );

        emit CallbackDispatched(eventId_, action_);
    }

    // ------------------------------------------------------------------
    // Admin / configuration
    // ------------------------------------------------------------------

    function setAgent(address agent_) external onlyOwner {
        agent = agent_;
    }

    function setRecipient(uint256 chainId_, address recipient_) external onlyOwner {
        callbackChainId = chainId_;
        callbackRecipient = recipient_;
    }

    function setBand(uint256 band_) external onlyOwner {
        band = band_;
    }

    function setAlpha(uint256 alpha_) external onlyOwner {
        alpha = alpha_;
    }

    /// @notice Recent origin prices, oldest first, for the agent's context.
    function getRecentPrices() external view returns (uint256[] memory) {
        uint256 n = eventsSeen < 16 ? eventsSeen : 16;
        uint256[] memory out = new uint256[](n);
        for (uint256 i = 0; i < n; ++i) {
            out[i] = recentPrices[(cursor + 16 - n + i) % 16];
        }
        return out;
    }

    function coverDebt() external {
        _coverDebt();
    }
}

/// @dev Minimal interface mirroring the destination contract, so the payload
///      selector is type-checked without a cross-chain import.
interface ISentinelDestination {
    function executeDecision(
        address reactive_,
        uint256 eventId_,
        uint8 action_,
        bytes32 decisionHash_,
        uint64 modelLatencyMs_,
        uint256 decidedAt_
    ) external;
}
