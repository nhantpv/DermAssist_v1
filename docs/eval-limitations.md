# Eval Limitations — Distribution Shift Acknowledgment

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
