# Retrieval calibration

Model: `bge-m3`

- **quality**: `k=20`, threshold `0.2`
- **context**: `k=10`, threshold `0.45`
- **balanced**: `k=20`, threshold `0.45`
- **abstention**: `k=20`, threshold `0.2`

`quality` is a potential pool profile; `context` is limited to k<=10 because runtime context is capped at 12. k=20 is never a final context recommendation.
Retrieval and abstention are reported separately; profiles are selected per model without cross-model score comparisons.
