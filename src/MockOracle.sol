// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

/// @title MockOracle — origin-chain price feed for the Sentinel demo.
/// @notice Emits PriceUpdated events that the Sentinel reactive contract
///         subscribes to on Reactive Lasna. In production this subscription
///         would target a real oracle or DEX pool; the event shape matches
///         common oracle feeds so the reactive side is unchanged.
contract MockOracle {
    address public owner;
    uint256 public price = 2000e18; // 18-decimal price, starts at $2000
    uint256 public updateCount;

    event PriceUpdated(address indexed token, uint256 price, uint256 timestamp);

    error NotOwner();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Push a new price for the watched token.
    function setPrice(uint256 price_) external onlyOwner {
        price = price_;
        ++updateCount;
        emit PriceUpdated(address(this), price_, block.timestamp);
    }

    /// @notice Push a series of prices in one tx (demo convenience).
    function setPrices(uint256[] calldata prices_) external onlyOwner {
        for (uint256 i = 0; i < prices_.length; ++i) {
            price = prices_[i];
            ++updateCount;
            emit PriceUpdated(address(this), prices_[i], block.timestamp);
        }
    }

    function transferOwnership(address newOwner_) external onlyOwner {
        owner = newOwner_;
    }
}
