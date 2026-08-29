
1. ~~Claude code session in Apply agent is blind to captcha~~ — root
   caused: the JS `browser_evaluate` detection script can't see into the
   cross-origin iframe reCAPTCHA renders in. Resolved by replacing the
   whole CAPTCHA section with a simple bounded-retry policy (try twice,
   then escalate) that doesn't depend on that detection script at all —
   see TECH_REQUIREMENT.md.
2. ~~Hallucination in DOB~~ — root caused: date of birth wasn't in the
   "never lie about" hard-rules list, and there was no real DOB in
   profile.json to answer with. Fixed: added `date_of_birth` to the
   profile schema and to the hard-rules list.
3. Broader hallucination pattern found via `filled_fields.json`: postal
   code, salary/CTC, and start date were all fabricated when the
   corresponding profile fields were `"FILL_IN"` placeholders — the agent
   doesn't treat that string as an absence signal. Fixed by filling in
   real values for all profile fields (no more placeholders remain) and
   simplifying the salary section to state real figures directly instead
   of a decision-tree that always produced a number.