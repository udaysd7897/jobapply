
1. ~~Hallucination in DOB~~ — root caused: date of birth wasn't in the
   "never lie about" hard-rules list, and there was no real DOB in
   profile.json to answer with. Fixed: added `date_of_birth` to the
   profile schema and to the hard-rules list.
2. Broader hallucination pattern found via `filled_fields.json`: postal
   code, salary/CTC, and start date were all fabricated when the
   corresponding profile fields were `"FILL_IN"` placeholders — the agent
   doesn't treat that string as an absence signal. Fixed by filling in
   real values for all profile fields (no more placeholders remain) and
   simplifying the salary section to state real figures directly instead
   of a decision-tree that always produced a number.
3. ~~Spawned apply-agent session refused to proceed, quoting `CLAUDE.md`
   back~~ — root caused: it inherited this repo as its `cwd`, so Claude
   Code auto-loaded this repo's own `CLAUDE.md` (which warns that "the
   apply agent" is a risky live action) as its project context, and
   talked itself out of the very task it was spawned to do. Fixed by
   giving the subprocess a `cwd` outside the repo — see
   TECH_REQUIREMENT.md.
