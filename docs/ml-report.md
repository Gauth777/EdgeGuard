# Synthetic ML evaluation — 2026-10-03

This is a reproducible software experiment, not evidence of industrial anomaly accuracy. The same simulator family generates normal training/calibration and independent-seed test sequences. No evaluation seed or abnormal sample is used to fit the forest or choose its threshold. The threshold and policy were not tuned after inspecting these results.

## Protocol

- Fit: 2,400 normal samples, seed 1101.
- Calibration: 1,200 separate normal samples, seed 2202; anomaly threshold is the 0.5th percentile of normal score_samples.
- Evaluation: seeds 3303, 4404, 5505, 6606; seven scenarios × four sequences × 150 seconds, paired between rules and hybrid.
- Both policies run through the real Store.ingest persistence/incident code. Critical events are immediate; warnings need three consecutive samples.
- Detection means an incident-open or abnormal-resumed transition within the labelled abnormal window. Delay is relative to its start; missed episodes have null delay.
- False incidents count those transitions outside labelled abnormal windows. Counts include pre/post-event normal periods. They are not per-sample false-positive percentages.
- Model warnings are statistical novelty, not diagnosed equipment faults.

## Results

| Scenario | Policy | Detected / abnormal episodes | False incident starts | Median detection delay |
|---|---|---:|---:|---:|
| normal | rules | No abnormal episode | 0 | — |
| normal | hybrid | No abnormal episode | 2 | — |
| noisy_normal | rules | No abnormal episode | 0 | — |
| noisy_normal | hybrid | No abnormal episode | 0 | — |
| missing | rules | No abnormal episode | 0 | — |
| missing | hybrid | No abnormal episode | 1 | — |
| critical | rules | 4/4 | 0 | 0.0 s |
| critical | hybrid | 4/4 | 1 | 0.0 s |
| subthreshold | rules | 0/4 | 0 | — |
| subthreshold | hybrid | 4/4 | 1 | 4.0 s |
| combination | rules | 0/4 | 0 | — |
| combination | hybrid | 4/4 | 1 | 4.0 s |
| healthy_shift | rules | No abnormal episode | 0 | — |
| healthy_shift | hybrid | No abnormal episode | 5 | — |

Each scenario represents four 150-second sequences (10 minutes total per policy). The four below-threshold episodes last 60 seconds each.

## Interpretation

- The hybrid detects below-threshold shifts and deliberately unusual combinations in all four runs each, with a four-second median delay from filtering plus confirmation. Rules alone detect neither scenario.
- Both policies immediately detect the four critical rule-breach episodes.
- The hybrid produces two false incident starts in the normal sequences and five in healthy-shift sequences. It must not be represented as production-calibrated.
- The noisy-normal test produces no false incidents in these four runs. This is a narrow test, not proof of general noise immunity.
- Missing vibration suspends inference during the missing window; the single false incident in that scenario occurs in a complete-data part of the sequence.
- A new healthy operating regime can look abnormal. Deployment needs broader normal data, operating-mode handling and machine-specific validation.

## Resource observations

- Artifact size: 1,038,944 bytes.
- Median full hybrid ingestion time: 3.307 ms.
- 95th percentile full hybrid ingestion time: 5.547 ms.
These timings include SQLite transactions and inference on this development host. They are not a fleet benchmark or target edge-device guarantee.

Model fingerprint: `2ebc0a6b1b3e937a`. The trained binary is generated locally and excluded from Git.

## Reproduce

```sh
python -m scripts.evaluate_ml
```

The complete per-sequence results are in [ml-evaluation.json](ml-evaluation.json). Metrics describe one fixed candidate and small synthetic evaluation. There is no claim of 100% real-world accuracy.
