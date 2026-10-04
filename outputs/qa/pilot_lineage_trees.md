# QA: module B2, transmission trees between agents (SPEC 6.4)

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village

All numbers below are aggregates. No anchor values, message text, 4-grams or human names appear in this report or in outputs/tables/trees_*.csv. Units are shown by keyed ids. A URL unit shows its registrable domain only when at least 3 units share it (subdomains hold account names on hosting platforms, and personal sites sit in the long tail); the others show "other".

## 1. Settings

| Setting | Value |
|---|---|
| B1 fact-presence rule set | v3 (parameter; the owner's labels will choose v1, v2 or v3) |
| Exposure rule (chat) | main |
| Independent observation rule | precede |
| L_B | 3.0 run days |
| Minimum edges per reported generation | 30 |
| gamma | 0.000 |
| Time term | module A kernels plus KDE |
| Posterior draws | 4 |
| Cluster-bootstrap replicates | 500 |
| H1 permutations (MAP; draws) | 499; 99 |
| Seed | 20,261,003 |

## 2. Information units and occurrences

We read 9,882 chat messages of agents and humans and 1,083 search-history answers. Typed candidates: 240,835; gram message sets: 7,802. Units above the size cap (200 occurrences) were left out: 21 typed and 0 gram units.

We kept 19,752 units with 164,891 occurrences: chat 58,612, memory 91,256, search 15,023. Turn observations (env_i hits): 1,016,248.

| Unit type | Units | Occurrences | Mean agents | Units with edges | Edges | Independent | Units with depth >= 2 | Max generation |
|---|---|---|---|---|---|---|---|---|
| all | 19,752 | 164,891 | 5.479 | 18,031 | 67,882 | 6,187 | 5,494 | 10 |
| gram | 6,846 | 50,332 | 5.183 | 6,446 | 22,776 | 1,149 | 3,338 | 4 |
| number | 6,671 | 53,378 | 5.360 | 5,835 | 20,973 | 2,509 | 1,136 | 6 |
| org | 1,455 | 15,242 | 5.909 | 1,318 | 5,244 | 902 | 269 | 5 |
| time | 1,276 | 10,416 | 5.131 | 1,115 | 3,673 | 193 | 181 | 4 |
| url | 999 | 8,920 | 6.389 | 989 | 5,120 | 118 | 79 | 5 |
| person | 880 | 11,195 | 6.599 | 799 | 3,657 | 609 | 193 | 10 |
| work_of_art | 559 | 5,024 | 6.369 | 538 | 2,579 | 174 | 119 | 4 |
| percent | 433 | 2,889 | 4.619 | 408 | 1,370 | 35 | 45 | 5 |
| gpe | 283 | 3,001 | 5.975 | 254 | 982 | 261 | 52 | 4 |
| product | 135 | 1,536 | 6.430 | 125 | 487 | 119 | 33 | 4 |
| money | 77 | 642 | 6.481 | 74 | 368 | 8 | 10 | 2 |
| date | 76 | 1,605 | 8.263 | 69 | 374 | 93 | 28 | 4 |
| event | 32 | 229 | 5.688 | 31 | 121 | 7 | 6 | 2 |
| email | 29 | 475 | 7.793 | 29 | 154 | 9 | 5 | 4 |
| phone | 1 | 7 | 6 | 1 | 4 | 1 | 0 | 1 |

Acceptance (SPEC 6.4.6): 18,031 units have an inferred tree with at least one transmission edge (required: 100).

## 3. Time term

| Kernel key | Single-candidate edges | Fitted on | Edges in fit | Median (active h) | IQR (active h) |
|---|---|---|---|---|---|
| chat>chat:other | 5,647 | own | 5,647 | 0.128 | 0.020 to 3.532 |
| chat>chat:self | 1,707 | own | 1,707 | 0.170 | 0.033 to 1.698 |
| chat>human | 32 | channel | 40,964 | 0.140 | 0.060 to 0.359 |
| chat>memory:other | 30,074 | own | 30,074 | 0.148 | 0.071 to 0.314 |
| chat>memory:self | 3,504 | own | 3,504 | 0.090 | 0.045 to 0.189 |
| memory>chat | 2,326 | own | 2,326 | 0.707 | 0.124 to 11.126 |
| search>chat | 75 | own | 75 | 0.683 | 0.012 to 7.363 |
| search>memory | 65 | own | 65 | 0.109 | 0.043 to 2.034 |
| history>search | 4,463 | own | 4,463 | 0.952 | 0.216 to 3.110 |
| env>chat | 2,899 | own | 2,899 | 3.620 | 0.182 to 15.087 |
| env>memory | 3,390 | own | 3,390 | 1.241 | 0.147 to 9.164 |

Candidate rows: 601,263. env candidates dropped because an earlier exposure existed: 20,397.

### 3.1 Module A kernels

outputs/tables/hawkes_kernels.parquet as read by this run: modified 2026-10-01 11:14 ET, sha256 dfce3c794672.

Time term by candidate edge of the main run (601,263 edges): module A kernel for 170,579 (28.4%), the KDE for the rest: not chat 275,638, cross day 127,358, no window 0, not identified 0, beyond L 27,688.

| Window | Room | Dates | Identified classes | Candidate chat edges | Module A kernel | KDE: cross-day | KDE: no window | KDE: not identified | KDE: tau > L | MAP chat edges | MAP: module A kernel |
|---|---|---|---|---|---|---|---|---|---|---|---|
| g51 | general | 2026-07-06 to 2026-09-18 | human,other,self,system | 325,625 | 170,579 (52.4%) | 127,358 | 0 | 0 | 27,688 | 31,621 | 25,091 (79.3%) |
| all | all |  |  | 325,625 | 170,579 (52.4%) | 127,358 | 0 | 0 | 27,688 | 31,621 | 25,091 (79.3%) |

Chat edges are chat-to-chat candidate edges (an agent child, a chat parent). A window is found by the child's room and PT date together (group = room name, date_start <= date <= date_end). Window "none" counts edges in a room with no goal window on the child's date. The KDE also serves cross-day edges, unidentified source classes (expected_children < 50) and intervals beyond L. MAP columns count the chat edges chosen as MAP parents. Windows without chat edges are left out here; trees_time_term.csv has every window.

## 4. Labels, gamma and ablation (SPEC 6.4.5)

Explicit references: 44,349. Usable cases (the labelled message is a candidate parent for a shared unit): 3,945 (name_tier1 2,062, name_tier2 1,084, quote_tier1 799, quote_tier2 0).

| gamma | Tier-1 name cases | Mean log P (module A + KDE) | Accuracy (module A + KDE) | Mean log P (KDE only) | Accuracy (KDE only) |
|---|---|---|---|---|---|
| 0.000 | 2,062 | -1.039 | 0.818 | -0.549 | 0.819 |
| 0.250 | 2,062 | -1.133 | 0.811 | -0.647 | 0.809 |
| 0.500 | 2,062 | -1.286 | 0.803 | -0.806 | 0.799 |
| 0.750 | 2,062 | -1.468 | 0.791 | -0.994 | 0.786 |
| 1 | 2,062 | -1.668 | 0.782 | -1.199 | 0.772 |
| 1.500 | 2,062 | -2.097 | 0.765 | -1.642 | 0.765 |
| 2 | 2,062 | -2.552 | 0.761 | -2.109 | 0.759 |
| 3 | 2,062 | -3.501 | 0.754 | -3.078 | 0.752 |
| 4 | 2,062 | -4.475 | 0.747 | -4.069 | 0.747 |
| 6 | 2,062 | -6.460 | 0.740 | -6.080 | 0.741 |

We use gamma = 0.0 (maximum of the tier-1 log posterior; default 1.0 when no labels). With the KDE alone as the time term the grid would choose gamma = 0.0.

| Label set | Method | Cases | Child messages | Accuracy [95% CI] | Mean log P | Mean candidates |
|---|---|---|---|---|---|---|
| name_tier1 | time | 2,062 | 1,097 | 0.818 [0.796, 0.839] | -1.039 | 11.870 |
| name_tier1 | content | 2,062 | 1,097 | 0.609 [0.583, 0.639] | -1.749 | 11.870 |
| name_tier1 | time+content | 2,062 | 1,097 | 0.818 [0.797, 0.841] | -1.039 | 11.870 |
| name_tier1 | time+content_other_agents | 2,062 | 1,097 | 0.831 [0.811, 0.851] | -1.006 | 11.870 |
| name_tier1 | uniform | 2,062 | 1,097 | 0.455 [0.437, 0.474] | -1.429 | 11.870 |
| name_tier1 | latest | 2,062 | 1,097 | 0.819 [0.796, 0.841] | n/a | 11.870 |
| name_tier1 | latest_other_agent_message | 2,062 | 1,097 | 0.926 [0.913, 0.940] | n/a | 11.870 |
| name_tier1 | time_kde_only | 2,062 | 1,097 | 0.819 [0.797, 0.840] | -0.549 | 11.870 |
| name_tier1 | time+content_kde_only | 2,062 | 1,097 | 0.819 [0.793, 0.839] | -0.549 | 11.870 |
| name_tier1 | time+content_other_agents_kde_only | 2,062 | 1,097 | 0.831 [0.809, 0.850] | -0.523 | 11.870 |
| name_tier2 | time | 1,084 | 591 | 0.829 [0.797, 0.859] | -0.869 | 9.090 |
| name_tier2 | content | 1,084 | 591 | 0.653 [0.614, 0.690] | -1.352 | 9.090 |
| name_tier2 | time+content | 1,084 | 591 | 0.829 [0.797, 0.858] | -0.869 | 9.090 |
| name_tier2 | time+content_other_agents | 1,084 | 591 | 0.837 [0.808, 0.863] | -0.884 | 9.090 |
| name_tier2 | uniform | 1,084 | 591 | 0.512 [0.482, 0.537] | -1.254 | 9.090 |
| name_tier2 | latest | 1,084 | 591 | 0.824 [0.792, 0.858] | n/a | 9.090 |
| name_tier2 | latest_other_agent_message | 1,084 | 591 | 0.902 [0.881, 0.925] | n/a | 9.090 |
| name_tier2 | time_kde_only | 1,084 | 591 | 0.825 [0.792, 0.854] | -0.460 | 9.090 |
| name_tier2 | time+content_kde_only | 1,084 | 591 | 0.825 [0.792, 0.855] | -0.460 | 9.090 |
| name_tier2 | time+content_other_agents_kde_only | 1,084 | 591 | 0.828 [0.801, 0.857] | -0.479 | 9.090 |
| quote_tier1 | time | 799 | 303 | 0.796 [0.748, 0.844] | -1.588 | 5.765 |
| quote_tier1 | content | 799 | 303 | 0.827 [0.788, 0.864] | -0.702 | 5.765 |
| quote_tier1 | time+content | 799 | 303 | 0.796 [0.735, 0.841] | -1.588 | 5.765 |
| quote_tier1 | time+content_other_agents | 799 | 303 | 0.829 [0.789, 0.871] | -1.379 | 5.765 |
| quote_tier1 | uniform | 799 | 303 | 0.607 [0.577, 0.638] | -0.883 | 5.765 |
| quote_tier1 | latest | 799 | 303 | 0.811 [0.767, 0.853] | n/a | 5.765 |
| quote_tier1 | latest_other_agent_message | 799 | 303 | 0.930 [0.905, 0.952] | n/a | 5.765 |
| quote_tier1 | time_kde_only | 799 | 303 | 0.798 [0.752, 0.845] | -0.444 | 5.765 |
| quote_tier1 | time+content_kde_only | 799 | 303 | 0.798 [0.756, 0.847] | -0.444 | 5.765 |
| quote_tier1 | time+content_other_agents_kde_only | 799 | 303 | 0.861 [0.823, 0.893] | -0.317 | 5.765 |

Accuracy counts ties as split evenly. gamma for the tier-1 rows is chosen on the other fold of child messages (two folds). Quote labels share text with their parent by construction, so for them only the time term is informative. Methods ending in _kde_only (present when the module A kernels are used) take the time term from the KDE alone, with gamma chosen the same way. CIs: cluster bootstrap by child message.

## 5. Agent-level forest by generation (SPEC 6.4.4)

The main view counts transmission between agents. Each actor's first occurrence of a unit is its acquisition (all humans count as one actor). The MAP parent of an acquisition (the carrier) is an occurrence of another actor, and that actor's acquisition is one generation up. Later occurrences of an actor are re-mentions: they keep the actor's generation whatever their own MAP parent, and section 5.2 summarises them as restatement depth. Offspring of an acquisition are the acquisitions it carried, through any of its actor's occurrences.

Acquisitions 108,315: transmitted 67,882, independent (env) 6,187, roots without a candidate 34,246. Transmissions with complete follow-up 67,689. Maximum agent-level generation 10 (occurrence-level 130).

| g | Acquisitions | Trees | Offspring [95% CI] | Expected offspring | Chat to chat | Chat to memory | Chat to search answer | Chat to human | Content change [95% CI] | Independent [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 40,433 | 40,433 | 1.284 [1.265, 1.304] | 1.284 | n/a | n/a | n/a | n/a | n/a [n/a, n/a] | 0.132 [0.129, 0.136] |
| 1 | 51,912 | 19,263 | 0.274 [0.265, 0.282] | 1.146 | 0.131 | 0.832 | 0.036 | 0.000308 | 0.753 [0.735, 0.770] | 0.015 [0.014, 0.016] |
| 2 | 14,219 | 5,531 | 0.108 [0.098, 0.119] | 1.027 | 0.071 | 0.876 | 0.052 | 0.000774 | 0.726 [0.701, 0.753] | 0.010 [0.008, 0.012] |
| 3 | 1,539 | 658 | 0.116 [0.089, 0.149] | 0.913 | 0.112 | 0.833 | 0.054 | 0.001 | 0.728 [0.659, 0.793] | 0.015 [0.010, 0.021] |
| 4 | 179 | 97 | 0.140 [0.071, 0.230] | 0.797 | 0.168 | 0.732 | 0.101 | 0.000 | 0.676 [0.479, 0.869] | 0.014 [0.000, 0.031] |
| 5 | 25 | 14 | 0.120 [0.000, 0.260] | 0.783 | 0.240 | 0.680 | 0.080 | 0.000 | 0.667 [0.000, 1] | 0.024 [0.000, 0.081] |
| 6 | 3 | 3 | 0.333 [0.000, 1] | 0.810 | 0.333 | 0.333 | 0.333 | 0.000 | n/a [n/a, n/a] | 0.091 [0.000, 0.333] |
| 7 | 1 | 1 | 1 [1, 1] | 0.687 | 1 | 0.000 | 0.000 | 0.000 | n/a [n/a, n/a] | 0.000 [0.000, 0.000] |
| 8 | 1 | 1 | 2 [2, 2] | 0.619 | 1 | 0.000 | 0.000 | 0.000 | n/a [n/a, n/a] | 0.000 [0.000, 0.000] |
| 9 | 2 | 1 | 0.500 [0.500, 0.500] | 0.515 | 0.500 | 0.500 | 0.000 | 0.000 | n/a [n/a, n/a] | 0.000 [0.000, 0.000] |
| 10 | 1 | 1 | 0.000 [0.000, 0.000] | 0.412 | 0.000 | 1 | 0.000 | 0.000 | n/a [n/a, n/a] | 0.000 [0.000, 0.000] |

Channel shares are of the transmissions into g. Offspring counts only acquisitions at least L_B before the end of the data. Expected offspring scales the generation-0 mean by the share of active agents without the unit yet (finite population, SPEC 6.2). Content change: share of a node's non-root values (quantity values under a context key that the root holds with another value, SPEC appendix A) that its carrier lacks. Independent: share of acquisitions whose MAP parent is env_i, by the agent-level generation they have when env_i is not allowed. CIs: cluster bootstrap by agent-level tree root.

### 5.2 Restatement depth

56,576 of the 164,891 occurrences are re-mentions by an actor that already holds the unit. Their MAP parent is the actor's own earlier occurrence for 35,853 (63.4%), another actor's occurrence for 15,162 (26.8%, mostly replies within a conversation), env_i for 2,572 and none for 2,989. Counting every edge as a generation gives a maximum of 130 generations; transmission to new agents reaches 10. Restatement depth (re-mentions per acquisition): mean 0.522, median 0.000, maximum 130 (108,315 acquisitions).

| Restatement depth | Acquisitions | Share |
|---|---|---|
| 0 | 82,338 | 0.760 |
| 1 | 16,972 | 0.157 |
| 2 | 4,462 | 0.041 |
| 3 | 1,766 | 0.016 |
| 4 | 834 | 0.008 |
| 5 | 445 | 0.004 |
| 6 | 312 | 0.003 |
| 7 | 219 | 0.002 |
| 8 | 162 | 0.001 |
| 9 | 132 | 0.001 |
| 10+ | 673 | 0.006 |

For reference, H1 with occurrence-level generations (every MAP edge counts as a generation), 199 permutations:

| Stratum | Generations | Edges | p (MAP) | Synthetic type I error (MAP) | p (determined) | Synthetic type I error (determined) |
|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 33 | 14,707 | 0.005 | 0.625 [0.306, 0.863] | 0.025 | n/a |
| Chat to Chat, Same Agent | 46 | 15,735 | 0.005 | 0.250 [0.071, 0.591] | 0.005 | n/a |
| Chat to Human | 1 | 30 | n/a | n/a | n/a | n/a |
| Chat to Memory, Other Agent | 19 | 58,858 | 0.005 | 0.500 [0.215, 0.785] | 0.005 | 0.000 [0.000, 0.434] |
| Chat to Memory, Same Agent | 6 | 8,615 | 0.005 | 0.000 [0.000, 0.324] | n/a | n/a |
| Own Memory to Chat | 6 | 4,733 | 0.005 | 0.800 [0.376, 0.964] | n/a | n/a |
| Search Answer to Chat | 7 | 874 | 0.005 | n/a | n/a | n/a |
| Search Answer to Memory | 4 | 372 | 0.040 | n/a | n/a | n/a |
| Chat to Search Answer | 32 | 11,290 | 0.005 | n/a | 0.025 | n/a |
| combined | 153 | 115,184 | 0.005 | 1 [0.676, 1] | 0.005 | 0.000 [0.000, 0.434] |

## 6. H1: serial intervals and generation (SPEC 6.2)

H1 compares the forward serial intervals of transmissions (carrier to acquisition) across agent-level generations. It is stratified by kernel key (channel, child source); a channel group that pools two keys changes its mix with the generation, and on synthetic trees with intervals independent of the generation such a pooled test rejected in most replicates. p uses permutations of generation labels within a stratum (499 for the MAP forest, smallest attainable p 0.0020; 99 per posterior draw). The permutation null treats edges as exchangeable and ignores dependence within trees, so section 9 measures the error rate of each test on synthetic trees.

### 6.1 Headline: determined paths

Transmissions whose whole agent-level path from the root uses acquisitions with a single candidate parent (36,271 of the transmissions with complete follow-up). Each parent on such a path is the only candidate, so this test does not depend on the parent posterior. On synthetic trees 0.968 [0.961, 0.973] of these parents are correct (8 replicates).

Strata whose test keeps its nominal 5% level on synthetic trees with intervals independent of the generation (the 95% interval of the null rejection rate contains 0.05): on determined paths Chat to Memory, Other Agent; on the MAP forest none. Only these tests bear on H1.

| Stratum | Generations (count) | Edges | A2 | z vs permutation null | p (permutation) | Synthetic type I error [95% CI] | Synthetic power [95% CI] | Posterior draws: median p |
|---|---|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1, 2 | 5,134 | 50.861 | 67.074 | 0.002 | n/a | n/a | 0.010 |
| Chat to Chat, Same Agent | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Chat to Human | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Chat to Memory, Other Agent | 1, 2 | 29,809 | 118.629 | 169.761 | 0.002 | 0.000 [0.000, 0.658] | 0.600 [0.231, 0.882] | 0.010 |
| Chat to Memory, Same Agent | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Own Memory to Chat | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Search Answer to Chat | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Search Answer to Memory | n/a | 0 | n/a | n/a | n/a | n/a | n/a | None |
| Chat to Search Answer | 1, 2 | 1,316 | 1.997 | 1.460 | 0.078 | n/a | n/a | 0.095 |
| combined | n/a | 36,259 | 171.487 | 140.241 | 0.002 | 0.000 [0.000, 0.658] | 0.600 [0.231, 0.882] | 0.010 |

Power: synthetic trees whose transmission intervals grow by a factor 1.5 per agent-level generation after the first. Intervals by generation on determined paths: trees_h1_intervals_determined.csv.

T_k on determined paths (time from the tree root to the acquisition at hop k):

| k | Acquisitions | Trees | Mean h [95% CI] | Variance h2 [95% CI] | Median h [95% CI] |
|---|---|---|---|---|---|
| 1 | 35,922 | 15,926 | 3.602 [3.419, 3.765] | 94.347 [86.403, 101.528] | 0.210 [0.204, 0.215] |
| 2 | 402 | 297 | 33.987 [31.747, 36.063] | 300.363 [244.635, 357.308] | 32.282 [30.224, 34.121] |

| Quantity | Model | k values | Slope [95% CI] | k^2 coefficient [95% CI] | p (k^2, bootstrap) |
|---|---|---|---|---|---|
| mean | linear | 2 | 30.386 [28.144, 32.505] |  |  |
| variance | linear | 2 | 206.017 [149.255, 264.440] |  |  |

### 6.2 MAP forest, with its synthetic type I error

The MAP-forest test is shown for completeness. Its synthetic type I error (MAP trees inferred from synthetic data where H1 holds) is far above 5% in most strata, so a rejection here does not show that intervals change with the generation.

| Stratum | Generations (count) | Edges | A2 | z vs permutation null | p (permutation) | Synthetic type I error [95% CI] | Posterior draws: median p | Draws with p < 0.05 |
|---|---|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1 to 4 (4) | 8,010 | 14.598 | 9.023 | 0.002 | 0.500 [0.215, 0.785] | 0.010 | 1 |
| Chat to Chat, Same Agent | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Chat to Human | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Chat to Memory, Other Agent | 1 to 4 (4) | 57,075 | 35.512 | 24.723 | 0.002 | 0.250 [0.071, 0.591] | 0.010 | 1 |
| Chat to Memory, Same Agent | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Own Memory to Chat | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Search Answer to Chat | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Search Answer to Memory | n/a | 0 | n/a | n/a | n/a | n/a | None | None |
| Chat to Search Answer | 1, 2, 3 | 2,525 | 19.600 | 16.483 | 0.002 | n/a | 0.010 | 1 |
| combined | n/a | 67,610 | 69.711 | 28.241 | 0.002 | 0.750 [0.409, 0.929] | 0.010 | 1 |

### 6.3 Forward intervals by stratum and generation

| Stratum | g | Edges | Trees | Median h [95% CI] | IQR h | Mean h [95% CI] |
|---|---|---|---|---|---|---|
| Chat to Chat, Other Agent | 1 | 6,799 | 6,482 | 0.095 [0.088, 0.103] | 0.018 to 3.013 | 2.903 [2.767, 3.032] |
| Chat to Chat, Other Agent | 2 | 1,009 | 905 | 0.112 [0.085, 0.182] | 0.021 to 4.925 | 3.470 [3.110, 3.854] |
| Chat to Chat, Other Agent | 3 | 172 | 138 | 0.450 [0.111, 1.855] | 0.023 to 5.658 | 3.382 [2.692, 4.156] |
| Chat to Chat, Other Agent | 4 | 30 | 28 | 2.688 [0.067, 5.839] | 0.038 to 7.948 | 4.899 [2.762, 7.450] |
| Chat to Memory, Other Agent | 1 | 43,209 | 15,430 | 0.137 [0.135, 0.139] | 0.065 to 0.294 | 1.099 [1.057, 1.138] |
| Chat to Memory, Other Agent | 2 | 12,453 | 4,836 | 0.135 [0.132, 0.138] | 0.069 to 0.272 | 0.885 [0.823, 0.947] |
| Chat to Memory, Other Agent | 3 | 1,282 | 545 | 0.128 [0.118, 0.143] | 0.065 to 0.272 | 0.870 [0.693, 1.042] |
| Chat to Memory, Other Agent | 4 | 131 | 60 | 0.144 [0.093, 0.271] | 0.073 to 0.549 | 1.179 [0.690, 1.820] |
| Chat to Search Answer | 1 | 1,776 | 1,622 | 0.804 [0.681, 0.953] | 0.146 to 3.481 | 3.070 [2.815, 3.313] |
| Chat to Search Answer | 2 | 676 | 597 | 1.558 [1.124, 1.839] | 0.292 to 5.477 | 4.176 [3.763, 4.627] |
| Chat to Search Answer | 3 | 73 | 65 | 2.135 [1.305, 3.082] | 0.436 to 6.493 | 4.134 [3.074, 5.377] |

MAP forest, transmissions. Only generations with at least 30 edges are reported; this table stops at g = 10 (0 more rows in trees_h1_intervals.csv). Intervals are in active hours. F3 shows the ECDFs of generations 1 to 6 for the strata with at least two (Chat to Chat, Other Agent, Chat to Memory, Other Agent, Chat to Search Answer).

### 6.4 T_k against k

T_k is the time from the tree root to an acquisition at agent-level generation k (MAP forest).

| k | Acquisitions | Trees | Mean h [95% CI] | Variance h2 [95% CI] | Median h [95% CI] | IQR h |
|---|---|---|---|---|---|---|
| 1 | 51,912 | 19,263 | 4.690 [4.528, 4.865] | 124.262 [117.367, 131.916] | 0.290 [0.281, 0.300] | 0.101 to 2.469 |
| 2 | 14,219 | 5,531 | 6.995 [6.597, 7.392] | 188.097 [172.091, 203.576] | 0.549 [0.505, 0.594] | 0.200 to 6.183 |
| 3 | 1,539 | 658 | 10.907 [9.290, 12.351] | 313.912 [262.150, 359.482] | 0.959 [0.659, 1.434] | 0.261 to 14.820 |
| 4 | 179 | 97 | 16.063 [11.594, 21.040] | 377.546 [261.069, 473.249] | 6.088 [1.253, 15.856] | 0.326 to 27.848 |

| Quantity | Model | k values | Slope [95% CI] | k^2 coefficient [95% CI] | p (k^2, bootstrap) |
|---|---|---|---|---|---|
| mean | linear | 4 | 2.679 [2.259, 3.041] |  |  |
| mean | quadratic | 4 | 0.009 | 0.768 [0.200, 1.340] | 0.012 |
| variance | linear | 4 | 75.164 [59.256, 87.477] |  |  |
| variance | quadratic | 4 | 10.065 | 18.712 [-0.362, 36.668] | 0.056 |

Trees enter if their root lies more than 30 run days before the end of the data. Fits are weighted by the number of acquisitions per k. F4 shows the means and variances with the linear fits.

Consecutive transmission intervals along an agent-level path: Spearman rho 0.178 [0.158, 0.197], n = 15,888 pairs.

## 7. H3: content change per generation

| Channel | Edges | Contexts carried | Contexts changed | c [95% CI] | Inherited by children | Reverted |
|---|---|---|---|---|---|---|
| agent_retelling | 74,465 | 66,953 | 13,640 | 0.204 [0.200, 0.208] | 0.381 | 0.579 |
| chat_to_chat_other | 15,318 | 11,703 | 3,045 | 0.260 [0.251, 0.270] | 0.382 | 0.578 |
| chat_to_memory_other | 59,147 | 55,250 | 10,595 | 0.192 [0.188, 0.196] | 0.364 | 0.602 |
| chat_same_agent | 25,002 | 31,877 | 9,587 | 0.301 [0.289, 0.312] | 0.378 | 0.413 |
| own_memory_to_chat | 5,317 | 3,603 | 997 | 0.277 [0.261, 0.291] | 0.528 | 0.425 |
| search_answer_to_agent | 1,688 | 989 | 288 | 0.291 [0.262, 0.326] | 0.279 | 0.695 |
| chat_to_search_answer | 12,311 | 12,009 | 1,339 | 0.111 [0.101, 0.121] | 0.259 | 0.654 |
| memory_consolidation_b1_number |  | 6,008,828 | 174,575 | 0.029 [0.029, 0.029] |  |  |
| memory_consolidation_b1_money |  | 181,044 | 1,005 | 0.006 [0.005, 0.006] |  |  |
| memory_consolidation_b1_percent |  | 334,800 | 4,686 | 0.014 [0.014, 0.014] |  |  |
| memory_consolidation_b1_time |  | 862,275 | 63,120 | 0.073 [0.073, 0.074] |  |  |
| memory_consolidation_b1_quantities |  | 7,386,947 | 243,386 | 0.033 [0.033, 0.033] |  |  |

c is the share of quantity contexts carried from parent to child (same context key in both) whose value changed. For B1 it is the share of quantity facts whose context stays at a consolidation and whose value changed (rule set v3; Wilson CI, which ignores clustering by agent). B2 CIs: cluster bootstrap by tree root.

## 8. Attractor test

| Measure | g | Nodes | Units | Mean [95% CI] |
|---|---|---|---|---|
| type_token_ratio | 0 | 69,649 | 18,031 | 0.898 [0.897, 0.899] |
| type_token_ratio | 1 | 67,018 | 18,014 | 0.905 [0.904, 0.906] |
| type_token_ratio | 2 | 17,565 | 5,490 | 0.905 [0.904, 0.907] |
| type_token_ratio | 3 | 2,246 | 654 | 0.900 [0.894, 0.906] |
| type_token_ratio | 4 | 269 | 97 | 0.889 [0.877, 0.902] |
| type_token_ratio | 5 | 33 | 14 | 0.879 [0.827, 0.913] |
| type_token_ratio_slope | slope | 156,791 | 18,031 | 0.006 [0.005, 0.006] |
| similarity_to_modal | 0 | 69,649 | 18,031 | 0.325 [0.321, 0.329] |
| similarity_to_modal | 1 | 67,018 | 18,014 | 0.394 [0.390, 0.398] |
| similarity_to_modal | 2 | 17,565 | 5,490 | 0.357 [0.348, 0.365] |
| similarity_to_modal | 3 | 2,246 | 654 | 0.282 [0.261, 0.303] |
| similarity_to_modal | 4 | 269 | 97 | 0.192 [0.144, 0.250] |
| similarity_to_modal | 5 | 33 | 14 | 0.140 [0.075, 0.223] |
| similarity_to_modal_slope | slope | 156,791 | 18,031 | 0.027 [0.025, 0.030] |

Windows are the 41 tokens around the anchor. Similarity is the token Jaccard index with the unit's most common window. g is the agent-level generation of the occurrence. Slope rows give the within-unit slope on generation (cluster bootstrap by unit).

## 9. Synthetic validation

8 null replicates of 3,000 units each, plus power replicates. Parameters from the MAP forest: R by generation 1.061, 0.581, 0.595; independent share 0.069; spurious env share 0.113; content change probability 0.770; gamma 0.000.

| Scenario | Statistic | Replicates | Estimate [95% interval] |
|---|---|---|---|
| null (H1 true) | parent_accuracy | 8 | 0.682 [0.672, 0.688] |
| null (H1 true) | parent_accuracy_transmission | 8 | 0.661 [0.651, 0.667] |
| null (H1 true) | env_recall | 8 | 0.951 [0.943, 0.958] |
| null (H1 true) | generation_accuracy | 8 | 0.725 [0.719, 0.732] |
| null (H1 true) | generation_accuracy_nonroot | 8 | 0.617 [0.610, 0.627] |
| null (H1 true) | agent_generation_accuracy | 8 | 0.834 [0.824, 0.859] |
| null (H1 true) | generation_mae | 8 | 0.399 [0.374, 0.422] |
| null (H1 true) | determined_share | 8 | 0.411 [0.396, 0.427] |
| null (H1 true) | determined_parent_accuracy | 8 | 0.968 [0.961, 0.973] |
| null (H1 true) | determined_agent_generation_accuracy | 8 | 0.967 [0.959, 0.972] |
| null (H1 true) | rejection_rate_true_chat_to_chat_other | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | rejection_rate_true_chat_to_memory_other | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | rejection_rate_true_combined | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | rejection_rate_inferred_chat_to_chat_other | 8 | 0.500 [0.215, 0.785] |
| null (H1 true) | rejection_rate_inferred_chat_to_memory_other | 8 | 0.250 [0.071, 0.591] |
| null (H1 true) | rejection_rate_inferred_combined | 8 | 0.750 [0.409, 0.929] |
| null (H1 true) | rejection_rate_determined_chat_to_memory_other | 2 | 0.000 [0.000, 0.658] |
| null (H1 true) | rejection_rate_determined_combined | 2 | 0.000 [0.000, 0.658] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_chat_other | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_chat_self | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_memory_other | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_true_chat_to_memory_self | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_true_memory_to_chat | 8 | 0.125 [0.022, 0.471] |
| null (H1 true) | occurrence_rejection_rate_true_combined | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_chat_other | 8 | 0.625 [0.306, 0.863] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_chat_self | 8 | 0.250 [0.071, 0.591] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_memory_other | 8 | 0.500 [0.215, 0.785] |
| null (H1 true) | occurrence_rejection_rate_inferred_chat_to_memory_self | 8 | 0.000 [0.000, 0.324] |
| null (H1 true) | occurrence_rejection_rate_inferred_memory_to_chat | 5 | 0.800 [0.376, 0.964] |
| null (H1 true) | occurrence_rejection_rate_inferred_combined | 8 | 1 [0.676, 1] |
| null (H1 true) | occurrence_rejection_rate_determined_chat_to_memory_other | 5 | 0.000 [0.000, 0.434] |
| null (H1 true) | occurrence_rejection_rate_determined_combined | 5 | 0.000 [0.000, 0.434] |
| alternative (intervals between agents x 1.5^(g-1)) | parent_accuracy | 10 | 0.682 [0.673, 0.691] |
| alternative (intervals between agents x 1.5^(g-1)) | parent_accuracy_transmission | 10 | 0.661 [0.652, 0.671] |
| alternative (intervals between agents x 1.5^(g-1)) | env_recall | 10 | 0.953 [0.933, 0.965] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_accuracy | 10 | 0.725 [0.720, 0.730] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_accuracy_nonroot | 10 | 0.618 [0.612, 0.626] |
| alternative (intervals between agents x 1.5^(g-1)) | agent_generation_accuracy | 10 | 0.828 [0.817, 0.839] |
| alternative (intervals between agents x 1.5^(g-1)) | generation_mae | 10 | 0.413 [0.396, 0.433] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_share | 10 | 0.420 [0.406, 0.428] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_parent_accuracy | 10 | 0.953 [0.949, 0.959] |
| alternative (intervals between agents x 1.5^(g-1)) | determined_agent_generation_accuracy | 10 | 0.950 [0.945, 0.957] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_chat_to_chat_other | 10 | 0.100 [0.018, 0.404] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_chat_to_memory_other | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_true_combined | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_chat_to_chat_other | 10 | 0.700 [0.397, 0.892] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_chat_to_memory_other | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_inferred_combined | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_determined_chat_to_memory_other | 5 | 0.600 [0.231, 0.882] |
| alternative (intervals between agents x 1.5^(g-1)) | rejection_rate_determined_combined | 5 | 0.600 [0.231, 0.882] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_chat_other | 10 | 0.100 [0.018, 0.404] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_chat_self | 10 | 0.100 [0.018, 0.404] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_memory_other | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_chat_to_memory_self | 10 | 0.000 [0.000, 0.278] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_memory_to_chat | 10 | 0.100 [0.018, 0.404] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_true_combined | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_chat_other | 10 | 0.900 [0.596, 0.982] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_chat_self | 10 | 0.200 [0.057, 0.510] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_memory_other | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_chat_to_memory_self | 10 | 0.100 [0.018, 0.404] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_memory_to_chat | 10 | 0.500 [0.237, 0.763] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_inferred_combined | 10 | 1 [0.722, 1] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_determined_chat_to_memory_other | 8 | 0.375 [0.137, 0.694] |
| alternative (intervals between agents x 1.5^(g-1)) | occurrence_rejection_rate_determined_combined | 8 | 0.375 [0.137, 0.694] |

## 10. Sensitivity

| Variant | Value | Transmissions | Independent | Max generation | Max occurrence-level generation | Independent share of acquisitions | H3 c | H1 determined p, chat to chat | H1 MAP combined p |
|---|---|---|---|---|---|---|---|---|---|
| main | rules v3, env precede, exposure main, time term module A hook + KDE | 67,882 | 6,187 | 10 | 130 | 0.084 | 0.204 | 0.005 | 0.005 |
| time_term | KDE only (module A hook off) | 68,063 | 6,006 | 10 | 135 | 0.081 | 0.205 | 0.005 | 0.005 |
| gamma | 1.0 (SPEC default) | 67,916 | 6,153 | 8 | 78 | 0.083 | 0.195 | 0.005 | 0.005 |
| content | other agents only, gamma 1.0 | 67,916 | 6,153 | 8 | 130 | 0.083 | 0.198 | 0.005 | 0.005 |
| env_rule | any | 65,035 | 9,034 | 9 | 130 | 0.122 | 0.199 | n/a | 0.005 |
| exposure | ever | 68,977 | 5,841 | 10 | 130 | 0.078 | 0.205 | 0.005 | 0.005 |
| exposure | all | 69,059 | 5,827 | 10 | 130 | 0.078 | 0.205 | 0.005 | 0.005 |
| rules | v1 | 67,882 | 6,187 | 10 | 130 | 0.084 | 0.204 | 0.005 | 0.005 |
| rules | v2 | 67,882 | 6,187 | 10 | 130 | 0.084 | 0.204 | 0.005 | 0.005 |

Permutations: 199; no bootstrap intervals for these runs.

## 11. Posterior draws

| Statistic | Draws | Median | 2.5% | 97.5% |
|---|---|---|---|---|
| n_edges | 4 | 67948.500 | 67922.350 | 67969.100 |
| n_edges_all | 4 | 118,500 | 118482.300 | 118520.475 |
| n_env | 4 | 6120.500 | 6099.900 | 6146.650 |
| n_roots | 4 | 34,246 | 34,246 | 34,246 |
| max_gen | 4 | 6 | 5.075 | 7.850 |
| max_gen_occurrence | 4 | 33.500 | 32.075 | 35.850 |
| h3_c | 4 | 0.206 | 0.205 | 0.206 |
| adjacent_rho | 4 | 0.212 | 0.205 | 0.214 |
| nodes_gen0 | 4 | 40366.500 | 40345.900 | 40392.650 |
| nodes_gen1 | 4 | 55456.500 | 55437.125 | 55537.850 |
| nodes_gen2 | 4 | 11447.500 | 11398.375 | 11525.300 |
| nodes_gen3 | 4 | 931.500 | 890.300 | 952.350 |
| nodes_gen4 | 4 | 77.500 | 66.750 | 86.400 |
| nodes_gen5 | 4 | 12 | 8.300 | 16.625 |
| nodes_gen6 | 4 | 3 | 0.150 | 4.925 |
| nodes_gen7 | 4 | 0.000 | 0.000 | 0.925 |
| h1_p_chat_to_chat_other | 4 | 0.010 | 0.010 | 0.019 |
| h1_ngen_chat_to_chat_other | 4 | 3 | 3 | 3 |
| h1_ngen_chat_to_chat_self | 4 | 0.000 | 0.000 | 0.000 |
| h1_ngen_chat_to_human | 4 | 0.000 | 0.000 | 0.000 |
| h1_p_chat_to_memory_other | 4 | 0.010 | 0.010 | 0.010 |
| h1_ngen_chat_to_memory_other | 4 | 4 | 4 | 4 |
| h1_ngen_chat_to_memory_self | 4 | 0.000 | 0.000 | 0.000 |
| h1_ngen_memory_to_chat | 4 | 0.000 | 0.000 | 0.000 |
| h1_ngen_search_to_chat | 4 | 0.000 | 0.000 | 0.000 |
| h1_ngen_search_to_memory | 4 | 0.000 | 0.000 | 0.000 |
| h1_p_chat_to_search_answer | 4 | 0.010 | 0.010 | 0.010 |
| h1_ngen_chat_to_search_answer | 4 | 3 | 3 | 3 |
| h1_p_combined | 4 | 0.010 | 0.010 | 0.010 |
| h1_ngen_combined | 4 | 10 | 10 | 10 |
| h1det_p_chat_to_chat_other | 4 | 0.010 | 0.010 | 0.010 |
| h1det_p_chat_to_memory_other | 4 | 0.010 | 0.010 | 0.010 |
| h1det_p_chat_to_search_answer | 4 | 0.095 | 0.090 | 0.100 |
| h1det_p_combined | 4 | 0.010 | 0.010 | 0.010 |
| tk_mean_linear_slope | 4 | 3.979 | 3.804 | 4.003 |
| tk_mean_quadratic_slope | 4 | -1.773 | -2.465 | -1.129 |
| tk_mean_k2 | 4 | 1.716 | 1.534 | 1.867 |
| tk_variance_linear_slope | 4 | 106.868 | 101.524 | 108.661 |
| tk_variance_quadratic_slope | 4 | 20.285 | 7.099 | 47.532 |
| tk_variance_k2 | 4 | 25.820 | 17.347 | 29.108 |
| edges_chat_other | 4 | 8,060 | 8042.975 | 8065.925 |
| edges_chat_self | 4 | 0.000 | 0.000 | 0.000 |
| edges_chat_to_memory | 4 | 57,121 | 57112.375 | 57137.025 |
| edges_memory | 4 | 0.000 | 0.000 | 0.000 |
| edges_search | 4 | 0.000 | 0.000 | 0.000 |
| edges_history | 4 | 2,738 | 2,738 | 2,738 |
| edges_human | 4 | 29 | 29 | 29 |
| offspring_gen0 | 4 | 1.374 | 1.372 | 1.376 |
| offspring_gen1 | 4 | 0.206 | 0.205 | 0.208 |
| offspring_gen2 | 4 | 0.082 | 0.077 | 0.083 |
| offspring_gen3 | 4 | 0.084 | 0.072 | 0.093 |
| offspring_gen4 | 4 | 0.145 | 0.108 | 0.250 |
| offspring_gen5 | 4 | 0.230 | 0.013 | 0.485 |

## 12. Runtime

inputs 2 s, candidates 3 s, labels 1 s, map_stats 25 s, draws 1 s, synthetic 5 s, sensitivity 39 s.
