// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title Hybrid blockchain attendance registry
// Stores session metadata, selected wallets, signed challenges and IPFS CIDs.
contract HybridAttendance {
    enum SessionStatus {
        None,
        Active,
        Closed
    }

    struct Session {
        uint256 id;
        bytes32 challenge;
        uint256 startTime;
        string modelCid;
        string logCid;
        SessionStatus status;
    }

    address public immutable coordinator;
    uint256 private nonce;

    mapping(uint256 => Session) private sessions;
    mapping(uint256 => address[]) private selectedStudents;
    mapping(uint256 => mapping(address => bool)) public isSelected;
    mapping(uint256 => mapping(address => bytes)) private responses;
    mapping(uint256 => address[]) private responders;

    event SessionStarted(
        uint256 indexed sessionId,
        bytes32 challenge,
        address[] selected,
        string previousModelCid
    );
    event ResponseSubmitted(uint256 indexed sessionId, address indexed student, bytes signature);
    event SessionClosed(uint256 indexed sessionId, string modelCid, string logCid);

    modifier onlyCoordinator() {
        require(msg.sender == coordinator, "only coordinator");
        _;
    }

    modifier activeSession(uint256 sessionId) {
        require(sessions[sessionId].status == SessionStatus.Active, "session not active");
        _;
    }

    constructor() {
        coordinator = msg.sender;
    }

    function startSession(
        uint256 sessionId,
        address[] calldata selected,
        string calldata previousModelCid
    ) external onlyCoordinator returns (bytes32 challenge) {
        require(sessionId != 0, "zero session id");
        require(sessions[sessionId].status == SessionStatus.None, "session exists");
        require(selected.length > 0, "empty selection");

        nonce += 1;
        // The assignment defines Challenge = hash(sessionID || nonce).
        challenge = keccak256(abi.encodePacked(sessionId, nonce));
        sessions[sessionId] = Session({
            id: sessionId,
            challenge: challenge,
            startTime: block.timestamp,
            modelCid: previousModelCid,
            logCid: "",
            status: SessionStatus.Active
        });

        for (uint256 i = 0; i < selected.length; i++) {
            address student = selected[i];
            require(student != address(0), "zero student");
            require(!isSelected[sessionId][student], "duplicate student");
            isSelected[sessionId][student] = true;
            selectedStudents[sessionId].push(student);
        }

        emit SessionStarted(sessionId, challenge, selected, previousModelCid);
    }

    function submitResponse(uint256 sessionId, bytes calldata signature)
        external
        activeSession(sessionId)
    {
        require(isSelected[sessionId][msg.sender], "student not selected");
        require(signature.length > 0, "empty signature");
        require(responses[sessionId][msg.sender].length == 0, "response exists");

        responses[sessionId][msg.sender] = signature;
        responders[sessionId].push(msg.sender);
        emit ResponseSubmitted(sessionId, msg.sender, signature);
    }

    function closeSession(uint256 sessionId, string calldata modelCid, string calldata logCid)
        external
        onlyCoordinator
        activeSession(sessionId)
    {
        require(bytes(modelCid).length > 0, "empty model CID");
        require(bytes(logCid).length > 0, "empty log CID");

        Session storage session = sessions[sessionId];
        session.modelCid = modelCid;
        session.logCid = logCid;
        session.status = SessionStatus.Closed;
        emit SessionClosed(sessionId, modelCid, logCid);
    }

    function getSession(uint256 sessionId) external view returns (Session memory) {
        require(sessions[sessionId].status != SessionStatus.None, "unknown session");
        return sessions[sessionId];
    }

    function getSelectedStudents(uint256 sessionId) external view returns (address[] memory) {
        return selectedStudents[sessionId];
    }

    function getResponders(uint256 sessionId) external view returns (address[] memory) {
        return responders[sessionId];
    }

    function getResponse(uint256 sessionId, address student) external view returns (bytes memory) {
        return responses[sessionId][student];
    }
}

