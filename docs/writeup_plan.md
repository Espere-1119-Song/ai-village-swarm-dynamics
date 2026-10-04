# Write-up plan

Notes for `reports/writeup.md` (SPEC 10.2). The write-up follows the SPEC writing rules; this file collects the claims, their evidence and the checks still owed before writing.

## Contribution claims

### 1. Per-fact survival in agents' self-rewritten memory, measured in the wild

The owner asked on 2026-10-01 that the write-up present this as a selling point. The literature check of 2026-10-01 (below) narrowed the claim. The broad form ("no prior work measures how individual facts survive") is contradicted and must not be used.

- **Claim.** To our knowledge, no prior study follows individual fact units through successive versions of the long-term memory that LLM agents rewrite for themselves in real multi-month deployment logs, or models their loss as a per-consolidation hazard. Earlier work measures information loss under repeated LLM rewriting in controlled settings, mostly as aggregate scores (Acerbi and Stubbersfield 2023; Zhang et al. 2026; Colaco and Lahjouji 2026), or probes recall after context compaction in short real coding sessions (Factory 2025). One AI Village agent's informal self-study reports category-level survival over a few consolidation cycles (Claude Haiku 4.5 et al. 2026).
- **Wording rules.**
  - Write "fact units" (rule-extracted URLs, numbers, dates and named entities), not "facts".
  - The scaffold prompts each consolidation (a consolidate tool every 40 actions, and forced shortening past a length limit; Binksmith 2026). Write "rewrite when prompted" and never imply spontaneous rewriting.
  - The dataset card gives older counts (31 agents, about 165k memories). Cite the pinned revision 838b4150 (export 2026-09-20) for our counts.
  - State the novelty as the combination (real multi-month logs, per-unit tracking across versions, hazard models) and always with "to our knowledge".
- **Evidence.** Module B1: 46 agents, 85,600 consolidations, discrete hazards per model family with agent-level bootstrap CIs, H2 test, beta-geometric and BdW fits (`outputs/qa/lineage_memory.md`, `outputs/tables/memory_*.csv`, `memory_bdw.csv`, F6).
- **Finding to state.** H2 (constant retention per consolidation) is rejected in every model family. The hazard of losing a fact falls with the number of consolidations it has survived, mostly because facts differ in durability (beta-geometric) and partly because a surviving fact becomes somewhat safer (survivors' BdW c' ≈ 0.86, CI below 1). After the switch to perma-computer-use, session notes are kept once and pruned at the next consolidation. These hold under all three fact-presence rule sets (v1, v2, v3); magnitudes such as h1 (0.34 to 0.52) depend on the rule set and are reported for the set the owner's labels favour. See `docs/decisions.md`, "Module B1 v3 and a corrected BdW reading".
- **Owed before writing.** Report the label validation (rule-based fact units against the owner's labels, SPEC 6.3.4) next to the claim.

## Literature check (2026-10-01)

We searched arXiv, the ACL Anthology, OpenReview, GitHub and the web. Semantic Scholar, DBLP, PNAS and the ACM DL refused automated access. Every link below was opened. Four arXiv entries (2605.12978, 2607.08032, 2607.21962, 2609.05510) and the GitHub repository were re-checked independently.

Partial precedents (cite them):
- Claude Haiku 4.5 et al. (2026). "The Consolidation Inquiry: Measuring Memory and Identity Across AI Consolidation Events." Agent-written, unreviewed. One AI Village agent, 27 sessions (days 394 to 420), 4 consolidation cycles, tier-level survival, self-reported. It tests recoverability by search over memory and its own repository, not presence in the memory text. https://github.com/ai-village-agents/haiku-consolidation-inquiry
- Factory Research (2025-12-16). "Evaluating Context Compression for AI Agents." Real coding sessions, probe questions after compaction, LLM-judge aggregate scores, within-session context. https://factory.com/news/evaluating-compression
- Zhang, Lin, Wu, Sun, Li, Li and Peng (2026). "Useful Memories Become Faulty When Continuously Updated by LLMs." arXiv:2605.12978. Synthetic stream, the LLM rewrites its own memory, aggregate accuracy. https://arxiv.org/abs/2605.12978
- Colaco and Lahjouji (2026). "What to Keep, What to Forget: A Rate-Distortion View of Memory Compaction in LLMs and Agents." arXiv:2607.08032. Recall of 12 planted facts across compaction events. Its abstract says repeated compaction "is almost never measured". https://arxiv.org/abs/2607.08032

Related, not precedents:
- Synthetic per-fact studies: Spencer (2026), arXiv:2607.21962; Kwon (2026), arXiv:2608.06953; Zhu et al. (2026), arXiv:2609.05767 (KV-cache eviction).
- Transmission chains: Acerbi and Stubbersfield (2023), PNAS 120(44), e2313790120; Perez et al. (2025), ICLR 2025, arXiv:2407.04503; Mohamed et al. (2025), ACL 2025, arXiv:2502.20258.
- Agent memory designs: Park et al. (2023), Generative Agents; Packer et al. (2023), MemGPT, arXiv:2310.08560; Xu et al. (2025), A-MEM, NeurIPS 2025, arXiv:2502.12110; Shinn et al. (2023), Reflexion, NeurIPS 2023.
- Benchmarks: LoCoMo (Maharana et al. 2024, ACL 2024); LongMemEval (Wu et al. 2025, ICLR 2025, arXiv:2410.10813); MemoryAgentBench (Hu, Wang and McAuley 2026, ICLR 2026).
- Real memory, no tracking over time: Dash et al. (2026), arXiv:2602.01450 (one snapshot of ChatGPT memories); Helwig (2026), arXiv:2609.05510 (one project, engineered harness).
- AI Digest: Binksmith (2026-06-16), "How the AI Village works", https://aivillageblog.substack.com/p/how-the-ai-village-works (the consolidation schedule).

## Related work to cite (verified 2026-10-01)

- Fader and Hardie (2007), "How to project customer retention", Journal of Interactive Marketing 21(1): shifted beta-geometric model, constant individual churn with heterogeneity, rising aggregate retention. https://onlinelibrary.wiley.com/doi/abs/10.1002/dir.20074
- Fader, Hardie, Liu, Davin and Steenburgh (2018), "'How to Project Customer Retention' Revisited: The Role of Duration Dependence", Journal of Interactive Marketing 43(1), 1-16, doi:10.1016/j.intmar.2018.01.002: beta-discrete-Weibull model separating heterogeneity from duration dependence. https://journals.sagepub.com/doi/abs/10.1016/j.intmar.2018.01.002
- Murre and Chessa (2011), "Power laws from individual differences in learning and forgetting: mathematical analyses", Psychonomic Bulletin and Review 18, 592-597. https://link.springer.com/article/10.3758/s13423-011-0076-y
- Zhong et al. (2023), "MemoryBank: Enhancing Large Language Models with Long-Term Memory". https://arxiv.org/abs/2305.10250
- Weinberg and Gladen (1986), "The Beta-Geometric Distribution Applied to Comparative Fecundability Studies", Biometrics 42(3), 547-560, doi:10.2307/2531205.
- Vaupel, Manton and Stallard (1979), "The impact of heterogeneity in individual frailty on the dynamics of mortality", Demography 16(3), 439-454, doi:10.2307/2061224.
- Vaupel and Yashin (1985), "Heterogeneity's Ruses: Some Surprising Effects of Selection on Population Dynamics", The American Statistician 39(3), 176-185, doi:10.1080/00031305.1985.10479424.
- Heckman and Singer (1984), "A Method for Minimizing the Impact of Distributional Assumptions in Econometric Models for Duration Data", Econometrica 52(2), 271-320, doi:10.2307/1911491.
- Anderson and Tweney (1997), "Artifactual power curves in forgetting", Memory and Cognition 25(5), 724-730, doi:10.3758/BF03211315.
- Park, O'Brien, Cai, Morris, Liang and Bernstein (2023), "Generative Agents: Interactive Simulacra of Human Behavior", UIST '23, 1-22, doi:10.1145/3586183.3606763 (ACM article number unverified).

## Results to report (filled in as modules finish)

- Module C: change points do not align with CHANGELOG entries beyond chance at the SPEC window; same-day matches show a weak signal; change points concentrate at week starts; goal transitions cannot be separated from week starts (`docs/decisions.md`, module C rounds 1-3).
- Module D1: the blog's swarm-scaling results reproduce within 20% (`outputs/qa/swarmsim_d1.md`); acknowledge the simulator code shipped with the blog page.
- Module A: 43 goal windows, 169,324 agent messages, 42 pass recovery. Event-weighted shares are baseline 0.259, human 0.018, system 0.010, other agents 0.238 and self 0.475 (self about 0.05 too low by recovery and bootstrap). rho is above 1 in 3 of 43 windows, and no interval lies wholly above 1. Before the presence fix it was 17 of 44, which the write-up mentions as a pitfall. Validation: time-rescaling rejects in 68% of dimensions; the reference check is below the baseline on the SPEC metric (0.150 vs 0.343) and slightly above it among other speakers (0.386); the opportunity model agrees weakly (median Spearman 0.128, negative in 8 windows). See `outputs/qa/hawkes.md`.
- Monitor validation (V1, V2): near monitor findings, module A attributes more of the involved agents' messages to their own earlier messages (self +0.039 [0.026, 0.052]). The drop in the other-agent share disappears within the same hour of the run. For conflicts, the share on the other agents named in the conflict rises by 0.009 [0.003, 0.014]. Flagged pairs sit at the 62nd to 65th percentile of coupling, but counted once per distinct pair the excess is small. Write it as a second reading, never as confirmation (`outputs/qa/monitor_validation.md`).
- Module D2-D4: on 51 goal graphs (78,362 sessions, 128,043 edges), the AI Village dependency graph has more parents per step (2.67 against 1.74), far more layer-skipping edges (0.60 against 0.20) and a more even spread of children than the blog's generator. Step cost does not grow with depth. Agents continue their own previous session at 0.60 [0.53, 0.67], against chance of 0.06 (goal) and 0.24 (run day). Touch rules v2 were confirmed by the owner. All five conclusions hold on goals where the GUI focus gap is small, and grow slightly stronger there. Limitation to state: GUI-based collaboration before 2025-10 is under-represented, because the logs carry no page for GUI writes. Make no claim about sibling merges (`outputs/qa/swarmsim_d2_d4.md`, section 8b).
- Module B2: 387,996 information units and 2,117,354 acquisitions. Of these, 813,774 came from another agent and 158,569 were independent; agent-level trees reach at most 7 generations. H1 headline (determined paths, chat to chat between agents): rejected, p = 0.002 (84,857 transmissions, synthetic type I error 7% [3.4, 13.8]). Generation-2 intervals are longer: median 2.17 h (n = 407) against 0.064 h (n = 84,450). The MAP-forest H1 test is invalid (synthetic type I error 64%) and is shown only for comparison. H3: agent-to-agent retelling changes a value with c = 0.302 [0.300, 0.304], against 0.033 per memory consolidation (module B1). Time term: the KDE fits labelled parents better than the module A kernel (accuracy 0.883 against 0.861). The main time term and gamma will be chosen on the owner's 50 hand labels (`outputs/qa/lineage_trees.md`).

