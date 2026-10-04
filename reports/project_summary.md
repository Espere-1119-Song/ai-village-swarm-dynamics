# Influence Between Agents in the AI Village

Enxin Song and Wenhao Chai

We ask how strongly LLM agents influence each other when they share a chat, a memory scaffold and a stream of goals for a year and a half. avsd turns the AI Village logs into one event table and measures influence through chat, information and shared work, plus the scaffolding changes that AI Digest documents. We apply it to the public export of AI Digest (2026), which holds 46 agents, 183,485 chat messages and 78,362 computer-use sessions from April 2025 to September 2026. The write-up's figures and tables give 95% confidence intervals.

## The answer

Agents influence each other through every channel we measure. In chat and shared work, though, each agent continues its own activity more often than it responds to others, and cascades between agents stay subcritical. Information passed between agents reaches about half the agents it could and changes along the way.

## Four channels

- **Chat.** We fit a multivariate Hawkes process to the chat. Self-excitation accounts for 47.5% of 169,324 agent messages and other agents for 23.8%. The agent-to-agent spectral radius stays below 1 in 39 of 42 accepted goal windows.
- **Information.** We build transmission trees of information units between agents and follow fact units through each agent's own memory. A unit acquired from another agent is passed on 0.235 times against 0.466 expected. On paths with a single candidate parent, serial intervals lengthen with generation, p = 0.002. The median from chat into another agent's memory grows from 0.142 active hours to 0.263 h. Retelling changes the value of 30.1% of 909,623 carried quantities. Inside each agent's memory, 34.0% of new fact units are lost at the first consolidation, mostly because units differ in durability.
- **Shared work.** We link computer-use sessions through the artifacts they write and read. Among 50,251 consecutive session pairs whose later session builds on earlier work, 60.2% continue the agent's own previous session. Random parents give at most 25.0%. Real task graphs also have 2.67 parents per step against 1.74 in the swarm-scaling simulator of Chai (2026).
- **Scaffolding changes.** We detect change points in 387 behavioural series. Of 2,314 change points, 1,929 lie within three run days of a CHANGELOG entry, against 1,969.5 expected by chance, p = 0.695. Entries are dense, with 81.2% of run days that close to one.

## How to run it

Two commands, `avsd ingest` and `avsd build-events`, build the event table from the Hugging Face export at a pinned revision. One command per analysis then writes aggregate tables, figures and a QA report, and `avsd report` assembles a self-contained HTML results browser. Every stochastic step uses a fixed seed. Raw text, labels and intermediate files stay under `data/`, outside version control.

## Limitations

The logs hold no prompts, so we measure serial intervals between occurrences instead of exposure times. The Hawkes model fits the timing of single agents poorly. On synthetic null data, the two determined-path tests of the transmission trees reject in 7.0% and 13.0% of replicates at the 5% level. Simple recency rules match the parent labels as well as the inferred posterior.

## Where to look

- `README.md` covers installation, data access, every command and its runtime.
- `reports/writeup.pdf`, also as `reports/writeup.md`, reports every result with intervals and sample sizes.
- The results browser at https://espere-1119-song.github.io/ai-village-swarm-dynamics/reports/ shows every table and figure by analysis.
- `reports/findings_zh.md` explains the findings in plain Chinese.

Please cite the data as AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village.
