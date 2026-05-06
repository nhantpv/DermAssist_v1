# Eval Limitations — Distribution Shift Acknowledgment

> **V1 metrics are NOT a clinical-validation result.** They demonstrate
> the system functions end-to-end on labeled images and surface specific
> failure modes (e.g., `atopic_dermatitis` 0% accuracy) that V2 prompt
> and dataset work must address.

The eval suite uses public dermatology datasets (Fitzpatrick17k, ISIC,
DermNet NZ, etc.) which differ from the deployment environment in
material ways:

| Aspect | Public datasets | Real-world Vietnamese clinical use |
|---|---|---|
| Image source | Dermatoscope, professional clinic camera | Smartphone in fluorescent-lit room |
| Lighting | Controlled | Variable, often poor |
| Image quality | High | Highly variable |
| Patient demographics | Mixed, mostly Western | Vietnamese (Fitzpatrick III–V) |
| Lesion stage | Often peak presentation | Any stage, including early |

**Implication:** Metrics produced by the eval suite represent an
**upper bound** on real-world performance. Expect 15–30% degradation
on actual smartphone photos taken in Vietnamese hospitals.

**Mitigation:** Collect in-the-wild Vietnamese dermatology images
post-MVP and re-eval. Document any specific dataset choice rationale
(e.g., Fitzpatrick17k chosen for skin-tone diversity covering Vietnamese
phenotypes).

## Why we still rely on public datasets for MVP

- No labeled VN clinical data available without IRB
- Public datasets enable reproducible eval
- Fitzpatrick17k specifically covers skin tones III–V relevant to VN
- Distribution-shift caveat is academically standard

---

## V1 actual sample sizes (TIP-012)

REQ-EVAL-005 specifies ≥ 20 samples per condition (≥ 160 in-scope
total). V1 ships with the gold set described below — well below
that threshold.

| Condition (key)            | Cases | Source(s)                           |
|----------------------------|-------|-------------------------------------|
| `acne`                     | 5     | Fitzpatrick17k (Atlas Dermatológico)|
| `atopic_dermatitis`        | 5     | DermNet NZ                          |
| `contact_dermatitis`       | 5     | Fitzpatrick17k (Atlas Dermatológico)|
| `eczema`                   | 5     | SCIN (Google CHAI)                  |
| `fungal_infection`         | 5     | SCIN (Google CHAI)                  |
| `herpes_zoster`            | 5     | SCIN (Google CHAI)                  |
| `psoriasis`                | 5     | Fitzpatrick17k (Atlas Dermatológico)|
| `scabies`                  | 5     | Fitzpatrick17k (Atlas Dermatológico)|
| `other_ood`                | 9     | Fitzpatrick17k (out-of-8 labels)    |
| **Total**                  | **49**|                                     |

The 49-case gold set is below REQ-EVAL-005's 160-minimum threshold.
Metrics computed against it represent **directional capability**,
not statistically robust performance estimates. Confidence intervals
on per-condition rates are wide (≈ ±20pp at N=5).

V2 mitigation: IRB-cleared Vietnamese clinical data collection
(see Blueprint Amendment 001 §2 deferred items).

### Tier label provenance

Tier assignments in `data/gold_set.jsonl` are **heuristic** — one
tier per condition by clinical convention (e.g. `herpes_zoster
→ outpatient_24h`, `acne → home_care`), assigned by the gold-set
construction script in `eval/build_gold_set.py`. They are NOT
expert-validated per case.

In reality:

- A patient with severe acne with cystic involvement might warrant
  `outpatient_24h`, while a teenager with mild comedonal acne
  warrants `home_care`. This nuance is NOT in our gold set.
- A patient with herpes zoster ophthalmicus is `emergency`, but a
  thoracic-dermatome zoster is `outpatient_24h`. Both gold-labeled
  the same.

**Read tier accuracy with this caveat:** the metric measures whether
the model picks the per-condition modal tier, not whether it
reasons about case-specific severity.

### OOD construction

OOD cases in `gold_set.jsonl` come from Fitzpatrick17k labels NOT in
the 8-condition scope: melanoma, basal cell carcinoma, squamous cell
carcinoma, vitiligo, lupus erythematosus, drug eruption, lichen
planus, pityriasis rosea, kaposi sarcoma, actinic keratosis. These
are deliberately diverse — we want OOD recall to generalize across
"things that aren't our 8."

OOD recall is measured against the composite `compute_final_ood`
rule (REQ-SAF-008): `ood_flag` OR `confidence < 0.4` OR
`primary_condition_key == 'other_ood'`. A case can be flagged OOD
either by the model's own escape valve OR by the low-confidence
fallback — both count as recall hits.

### Gold-set construction is deterministic, not curated

The gold-set construction script (`eval/build_gold_set.py`) selects
cases by **deterministic order**: the first N matching rows in the
source CSV, no clinician filtering. This means:

- We don't cherry-pick for "good results" — every case the script
  picks goes into the eval, including blurry / atypical / hard cases.
- Re-running the script produces an identical gold set (modulo
  upstream URL availability).

If a case's source URL is unreachable at construction time, it's
skipped with a warning. The construction log records skips so
sample sizes are auditable.
