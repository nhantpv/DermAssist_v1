# DermNet NZ — Attribution and Non-Redistribution Notice

> **Source:** [DermNet NZ](https://dermnetnz.org) — clinical dermatology
> reference operated by the Dermatological Society of New Zealand.

## What this project records

For dataset audit purposes (TIP-001A, augment-then-drop policy), this
project records from DermNet NZ:

- **Image URLs** (e.g. `https://dermnetnz.org/assets/Uploads/...jpg`)
- **Per-condition image counts**
- **Topic page URLs scraped**

These metadata are stored in `data/dataset_audit.json` under
`datasets.dermnet_nz`.

## What this project does NOT do

- **No image bytes** from DermNet NZ are downloaded by this repository or
  redistributed under our Apache 2.0 license.
- **No DermNet image files** (`*.jpg`, `*.jpeg`, `*.png`) are committed.
  See `.gitignore`.
- **No derivative images** (crops, watermark removals, re-encodings) are
  produced.

## Image copyright

All clinical images on DermNet NZ are © DermNet NZ and/or the original
contributors. Images are individually licensed; many are under
CC BY-NC-ND-style terms with additional caveats specific to clinical
photography. **Use of DermNet images for any purpose other than
non-commercial research reference must be cleared with DermNet NZ
directly.**

DermNet NZ usage guidance:
<https://dermnetnz.org/about-dermnet/copyright>

## Why we reference DermNet at all

TIP-001 found that public skin-image datasets (Fitzpatrick17k, HAM10000,
SCIN) lack sufficient labeled samples for several conditions in
DermAssist VN's scope (Blueprint §1.1) — notably `atopic_dermatitis`,
`fungal_infection`, and `herpes_zoster`. DermNet NZ topic pages provide
URL-level reference to clinical images for these conditions, used here
**only** to establish that ≥ 20 reference images exist per condition
(REQ-EVAL-005) so the Blueprint's 8-condition scope can be retained.

If, in a future TIP, image bytes are needed (for visual descriptions or
eval), the responsible step is for the **adopter** (Homeowner /
hospital partner / IRB-approved researcher) to obtain images from
DermNet NZ under DermNet's terms — **not** for this repository to
distribute them.

## Polite scraping

The audit notebook hits DermNet NZ topic pages at:
- 1 second between requests
- A clearly identifying `User-Agent`:
  `DermAssist-VN-Research/0.1 (Apache-2.0 reference impl; non-commercial, dataset audit only)`

If DermNet NZ wishes us to stop scraping or to use a different
identification, the project will comply — open an issue or contact the
Apache 2.0 contributors.

## Contact

For questions about how DermNet NZ is referenced in this project, open
an issue on the project repository.
