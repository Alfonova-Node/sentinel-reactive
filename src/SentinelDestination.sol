// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

import { IPayable } from "@reactive/src/interfaces/IPayable.sol";
import { AbstractCallback } from "@reactive/src/base/AbstractCallback.sol";

/// @title SentinelDestination — receives Sentinel's AI decisions on the
///        destination chain and applies them to a simulated portfolio.
/// @notice Each callback carries the model's action plus the decision hash,
///         giving an on-chain audit trail of what the neural network decided
///         and when. Actions move a simulated exposure state so the full
///         loop is observable on a block explorer.
contract SentinelDestination is AbstractCallback {
    event DecisionExecuted(
        address indexed reactiveContract,
        uint256 indexed eventId,
        uint8 action,
        bytes32 decisionHash,
        uint64 modelLatencyMs,
        uint256 decidedAt,
        uint256 executedAt,
        uint256 exposureAfter
    );

    string[3] public ACTION_NAMES = ["HOLD", "REDUCE", "ALERT"];

    /// @notice Simulated exposure in basis points (10000 = fully deployed).
    uint256 public exposureBps = 10000;
    uint256 public decisionsExecuted;
    mapping(uint256 => bool) public seenEvents;

    error BadAction();
    error DuplicateEvent();

    constructor(
        IPayable callbackProxy_,
        address callbackSender_
    ) payable AbstractCallback(callbackProxy_, callbackSender_) {}

    /// @notice Owner-only drain of stranded native balance (testnet hygiene).
    function rescue(address payable to_) external {
        require(msg.sender == owner, "only owner");
        require(to_ != address(0), "zero dst");
        uint256 amount = address(this).balance;
        require(amount > 0, "nothing to rescue");
        to_.transfer(amount);
    }

    /// @notice Deployer, kept for rescue() access control.
    address public immutable owner = msg.sender;

    function executeDecision(
        address reactive_,
        uint256 eventId_,
        uint8 action_,
        bytes32 decisionHash_,
        uint64 modelLatencyMs_,
        uint256 decidedAt_
    ) external onlyServiceProvider onlyCallbackSender(reactive_) {
        if (action_ > 2) revert BadAction();
        if (seenEvents[eventId_]) revert DuplicateEvent();
        seenEvents[eventId_] = true;

        // Apply the action to the simulated exposure state.
        if (action_ == 1) {
            // REDUCE: cut exposure by 25%, floored at zero.
            uint256 cut = exposureBps > 2500 ? 2500 : exposureBps;
            exposureBps -= cut;
        } else if (action_ == 2) {
            // ALERT: de-risk harder, cut by 50%.
            uint256 cut = exposureBps > 5000 ? 5000 : exposureBps;
            exposureBps -= cut;
        }
        // HOLD leaves exposure unchanged.

        ++decisionsExecuted;
        emit DecisionExecuted(
            reactive_,
            eventId_,
            action_,
            decisionHash_,
            modelLatencyMs_,
            decidedAt_,
            block.timestamp,
            exposureBps
        );
    }

    function actionName(uint8 action_) external view returns (string memory) {
        return ACTION_NAMES[action_];
    }

    function coverDebt() external {
        _coverDebt();
    }
}
