pragma circom 2.1.6;

include "../node_modules/circomlib/circuits/comparators.circom";
include "../node_modules/circomlib/circuits/poseidon.circom";

// Fixed-point scale is 1000. For example E=0.812 is represented as 812.
// weightedError = sum(alpha_i * (S_real_i - S_hat_i)^2)
// e_i < epsilon is equivalent to weightedError < epsilonScaled * 1000^2.
template ReadinessProof() {
    // Private witness.
    signal input E;
    signal input Q;
    signal input D;
    signal input identitySecret;

    // Public session parameters and identity binding.
    signal input shatE;
    signal input shatQ;
    signal input shatD;
    signal input alphaE;
    signal input alphaQ;
    signal input alphaD;
    signal input errorBound;
    signal input sessionId;
    signal input identityCommitment;
    signal input nullifier;

    signal output ready;
    signal diffE;
    signal diffQ;
    signal diffD;
    signal squareE;
    signal squareQ;
    signal squareD;
    signal weightedE;
    signal weightedQ;
    signal weightedD;
    signal weightedError;

    // Every state component is in [0, 1000].
    component realRanges[3];
    component estimateRanges[3];
    for (var i = 0; i < 3; i++) {
        realRanges[i] = LessThan(11);
        estimateRanges[i] = LessThan(11);
    }
    realRanges[0].in[0] <== E;
    realRanges[1].in[0] <== Q;
    realRanges[2].in[0] <== D;
    estimateRanges[0].in[0] <== shatE;
    estimateRanges[1].in[0] <== shatQ;
    estimateRanges[2].in[0] <== shatD;
    for (var j = 0; j < 3; j++) {
        realRanges[j].in[1] <== 1001;
        estimateRanges[j].in[1] <== 1001;
        realRanges[j].out === 1;
        estimateRanges[j].out === 1;
    }

    alphaE + alphaQ + alphaD === 1000;

    diffE <== E - shatE;
    diffQ <== Q - shatQ;
    diffD <== D - shatD;
    squareE <== diffE * diffE;
    squareQ <== diffQ * diffQ;
    squareD <== diffD * diffD;
    // Keep every R1CS constraint quadratic by separating the three products.
    weightedE <== alphaE * squareE;
    weightedQ <== alphaQ * squareQ;
    weightedD <== alphaD * squareD;
    weightedError <== weightedE + weightedQ + weightedD;

    component belowThreshold = LessThan(32);
    belowThreshold.in[0] <== weightedError;
    belowThreshold.in[1] <== errorBound;
    belowThreshold.out === 1;
    ready <== belowThreshold.out;

    // Bind the proof to an enrolled device secret and make it session-specific.
    component identityHasher = Poseidon(1);
    identityHasher.inputs[0] <== identitySecret;
    identityHasher.out === identityCommitment;

    component nullifierHasher = Poseidon(2);
    nullifierHasher.inputs[0] <== identitySecret;
    nullifierHasher.inputs[1] <== sessionId;
    nullifierHasher.out === nullifier;
}

component main {public [
    shatE,
    shatQ,
    shatD,
    alphaE,
    alphaQ,
    alphaD,
    errorBound,
    sessionId,
    identityCommitment,
    nullifier
]} = ReadinessProof();
