# Human baseline — cad condition (NOT EXECUTED; format placeholder only)

> **Status: Not executed.** This repository contains no human expert ratings.
> Synthetic format-example rows (`_r1` / `_r2`) were removed to prevent confusion
> with actual experimental data and to remain consistent with Section 7 of the
> manuscript (no human expert evaluation conducted; see `benchmarks/human_eval/PROTOCOL.md` §6.3).
>
> Authoritative split in `benchmarks/human_eval/answer_key_cad.csv`:
> - **Scored cases**: `28` (`18` defective + `10` compliant)
> - **Practice cases**: `4` (`2` defective + `2` compliant), excluded from scoring
> - **Total anonymized files**: `32` (`CASE-01`–`CASE-32`)
>
> To populate this file in future work, recruit `>= 3` independent mechanical
> drafters per `benchmarks/human_eval/PROTOCOL.md` and run
> `python scripts/analyze_human_eval.py --condition cad rater1.csv rater2.csv rater3.csv`.
