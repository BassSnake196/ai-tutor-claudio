# Retrieval calibration

Model: `nomic-embed-text`

- **quality**: `k=10`, threshold `0.2`
- **context**: `k=10`, threshold `0.2`
- **balanced**: `k=10`, threshold `0.2`
- **abstention**: `k=10`, threshold `0.2`

`quality` is a potential pool profile; `context` is limited to k<=10 because runtime context is capped at 12. k=20 is never a final context recommendation.
Retrieval and abstention are reported separately; profiles are selected per model without cross-model score comparisons.
