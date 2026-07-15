# Hybrid Deterministic Search with Offline Optimal Residual Compilation: Exhaustive Closure Proofs for Finite Constraint-Satisfaction Games

**Abstract.** We study deterministic decision-making in finite constraint-satisfaction games in which an agent must identify a hidden ground truth drawn from a known, bounded universe by sequentially querying a black-box oracle. Each query returns a structured observation that partitions the remaining hypotheses. Because the hypothesis space is finite and the observation function is deterministic and publicly known, the problem admits both an exact optimal solution (adversarial minimax over the hypothesis set) and a fast, explainable heuristic approximation. The central tension is that the exact solver is intractable as a general online procedure, while the heuristic, though efficient and near-optimal on average, fails on a small, *identifiable* set of residual instances.

We present a hybrid framework that resolves this tension. A vectorized, information-theoretic heuristic (expected information gain penalized by worst-case partition size, with a posterior win-probability term) is the default online policy. Offline, we exhaustively enumerate the belief states reachable under the heuristic, detect the residual instances on which it violates the turn contract, and compile each residual cluster into a precomputed exact-minimax decision table. At runtime the live belief is matched against the compiled tables; on a match the engine defects from the heuristic to a provably-optimal move, otherwise it follows the heuristic. We enforce strict isolation across six mutually exclusive domains ({normal, hard} × {0, 1, 2 external hints}), prove each domain closes under a six-turn contract, and verify the claim through a cached, version-stamped closed-loop replay of **47,814** simulated games (zero failures, worst case six turns). The result is a solver that is simultaneously efficient, explainable, fully deterministic, and *provably complete* on every reachable instance. We report a quantitative architectural analysis: the compiled knowledge comprises 17,911 decision nodes (≈644 KB) covering a residual population of 30 words (1.30% of the universe), while 98.70% of the space is closed by the heuristic alone; the mean solve depth is 3.32 turns with an effective average branching factor of ≈10.3.

---

## 1. Introduction

Deterministic reasoning over finite spaces occupies a privileged position in artificial intelligence. Unlike continuous or open-world settings, finite problems admit exhaustive validation: every reachable state can, in principle, be visited, and every decision can be justified against a complete enumeration of outcomes. This property makes finite decision problems an ideal testbed for the scientific study of *hybrid search*, the combination of efficient approximative policies with exact optimal correction, and for the discipline of *knowledge compilation*, in which expensive inference is shifted offline so that online behavior reduces to a lookup.

We begin not with a game but with the abstract setting. Let a hidden state $s^\star$ be drawn from a finite, publicly known universe $\mathcal{C}$ of cardinality $N = |\mathcal{C}|$. An agent may, at each step $t = 1, 2, \dots, T$, issue a *query* $g_t$ from a context-dependent set of legal queries. The environment responds with a deterministic observation $o_t = \Phi(g_t, s^\star)$, where $\Phi$ is a fixed, public feedback function. The agent maintains a *belief state* $\mathcal{K}_t \subseteq \mathcal{C}$, the set of hypotheses still consistent with all observations, and wins when $\mathcal{K}_t$ collapses to the singleton $\{s^\star\}$ and that hypothesis is subsequently uttered.

Two desiderata compete. **Completeness** demands identification within a hard turn budget $T_{\max}$ on *every* instance. **Efficiency** demands that per-step decision cost remain low, so the solver is usable interactively and scales to exhaustive verification. **Explainability** demands that each decision be interpretable as either a well-understood information-theoretic move or a provably-optimal one. **Reproducibility** demands byte-identical behavior across processes, threads, and hardware layouts.

The exact solution is, in principle, available: the problem is a two-player zero-sum game in which the agent minimizes, and an adversarial nature maximizes, the number of queries required to force identification. But the reachable belief space is, in the worst case, exponential in $N$, and exact minimax is intractable as a general online procedure. The practical literature has therefore favored heuristics: entropy maximization, worst-case partition minimization, frequency/expected-value weighting, which are cheap and effective *on average* but lack a completeness guarantee.

Our central thesis is that the heuristic and the exact solver need not be opposed. We retain the heuristic as the *default hot path* while eliminating its residual incompleteness through offline compilation. The contributions, each developed in a dedicated section, are:

1. **Hybrid deterministic search architecture (§5 to §6).** A deterministic, vectorized scoring policy blends expected information gain, worst-case partition size, and posterior win-probability into a single scalar utility with mode-dependent penalties. This is the online default; an exact minimax solver is invoked only where necessary.
2. **Selective offline knowledge compilation (§7).** We define the *residual region* as the set of belief states reachable under the heuristic for which the heuristic violates the turn contract. We prove this region is finite, small, and *isolatable*, and we precompute an exact minimax decision table for each residual cluster. Runtime reduces to a hash lookup against the compiled tables.
3. **Hard-mode shredding via out-of-universe queries (§7.3).** We extend the legal query set for residual correction to include *auxiliary* dictionary words (outside the answer universe) that are consistent with all prior feedback, splitting otherwise-inseparable sibling clusters. We prove these queries are legal under the problem's hard-mode rule.
4. **Strict domain isolation (§11).** The problem is partitioned into six mutually exclusive, collectively exhaustive domains, each a frozen specification referencing only its own configuration and tables, so that repairing one domain cannot regress another.
5. **Exhaustive verification methodology (§13).** A closed-loop replay gate simulates every universe element under every legal configuration of each domain, proving 100% solvability within the turn budget (47,814 games, zero failures).
6. **Quantitative architectural analysis (§14, §16).** We report measurable structural metrics: residual-state count, lookup-table coverage, decision reuse, candidate-set reduction, branching factor, heuristic-activation frequency, offline-knowledge size, and runtime-lookup frequency, analyzing the architecture itself, not only solver performance.
7. **Reproducible benchmark framework (§17).** Deterministic execution, version-stamped caching, in-memory-only state, and static artifacts make every reported result regenerable from the committed repository.

---

## 2. Problem Formulation

### 2.1 Universe, Queries, and Observations

Let $\Sigma$ be a finite alphabet and $\ell$ a fixed word length. A *word* is an element of $\Sigma^\ell$. The **candidate set** (universe) is a finite subset $\mathcal{C} \subset \Sigma^\ell$ of cardinality $N = |\mathcal{C}|$. The hidden ground truth is a fixed but unknown element $s^\star \in \mathcal{C}$.

A **query** $g \in \Sigma^\ell$ is an arbitrary word. On issuing $g$, the agent receives an **observation** $\Phi(g, s^\star) \in \mathcal{O}$, where the observation space is the set of position-wise feedback patterns. We encode each position $i \in \{1,\dots,\ell\}$ with a ternary symbol

$$
\phi_i(g, s^\star) \in \{0,1,2\},
$$

where $2$ denotes an exact positional match (green), $1$ a present-but-misplaced symbol (yellow), and $0$ absence (grey). The full observation is the base-3 integer

$$
o = \Phi(g, s^\star) = \sum_{i=1}^{\ell} \phi_i(g, s^\star)\, 3^{\,i-1} \in \{0,1,\dots,3^\ell-1\}.
$$

For $\ell = 5$ this yields $|\mathcal{O}| = 3^5 = 243$ distinct feedback patterns. The feedback function $\Phi$ is deterministic, symmetric in its implementation, and known to both agent and verifier.

### 2.2 Knowledge State, Transition, and Policy

The **knowledge state** (belief) at step $t$ is the set of hypotheses consistent with all observations so far:

$$
\mathcal{K}_t = \bigl\{ s \in \mathcal{C} \;:\; \forall\, \tau \le t,\; \Phi(g_\tau, s) = o_\tau \bigr\},
\qquad \mathcal{K}_0 = \mathcal{C}.
$$

The **transition** induced by query $g_t$ and observation $o_t$ is the deterministic projection

$$
\mathcal{T}(\mathcal{K}_t, g_t, o_t) = \bigl\{ s \in \mathcal{K}_t \;:\; \Phi(g_t, s) = o_t \bigr\}
= \mathcal{K}_{t+1}.
$$

A **policy** is a mapping $\pi : \mathcal{K}_t \mapsto g_t$ selecting the next query. The policy wins at step $t$ if $g_t = s^\star$ (equivalently $|\mathcal{K}_t| = 1$ and the unique element is uttered).

### 2.3 External Constraints (Hints)

Certain configurations admit **external constraint revelation**: a distinguished letter $h$ is disclosed, imposing the additional filter

$$
\mathcal{K}_t \;\leftarrow\; \mathcal{K}_t \cap \{ s \in \mathcal{C} : h \in s \}.
$$

We consider a fixed hint rule restricting revelation to exactly one consonant and one vowel drawn from the true word's own letters. The hint budget $b \in \{0,1,2\}$ is a domain parameter; hint sets are enumerated exhaustively over all combinations the true word admits.

### 2.4 Search Objective

Define the **decision depth** $d(\mathcal{K}_t, \pi)$ as the number of additional queries required under policy $\pi$ to force $|\mathcal{K}| = 1$ and utter the answer. The **worst-case objective** is

$$
J^\star(\mathcal{K}) = \min_{g \in \mathcal{G}} \max_{o \in \mathcal{O}} \bigl( 1 + d(\mathcal{T}(\mathcal{K}, g, o), \pi^\star) \bigr),
$$

where $\pi^\star$ is the optimal (minimax) continuation. The **contract** is $J^\star(\mathcal{C}) \le T_{\max}$ for budget $T_{\max} = 6$. Our central claim is that a hybrid policy $\hat\pi$ satisfies

$$
\forall\, s^\star \in \mathcal{C},\; \forall\, \text{legal config } \delta \in \Delta,\qquad
\text{turns}_{\hat\pi}(s^\star, \delta) \le T_{\max},
$$

where $\Delta$ is the set of six domains (§4, §11).

---

## 3. Related Work

We position this work against the literature not as a survey but as a claim about *where it belongs*: at the intersection of **knowledge compilation** and **hybrid search**, applied to finite **constraint-satisfaction / interactive-diagnosis** problems.

**Entropy maximization and expected information gain.** Shannon-entropy ranking of queries (Berger et al.; the standard "best guess" heuristic) minimizes *expected* query count via $H(g\mid\mathcal{K}) = -\sum_b p_b\log_2 p_b$. *Similarity:* our utility's $H$ term is exactly this. *Difference:* entropy is a mean-case objective with no worst-case guarantee; a two-element pool can strand the higher-frequency sibling. *Assumption:* beliefs are diffuse enough that expected reduction dominates. *Limitation:* fatal on tight sibling clusters, precisely the residual we compile away.

**Minimax / worst-case search.** The adversarial formulation (Bernardini & Goldberg; Bonthron's optimal Wordle analysis) minimizes the largest resulting bucket and yields a guaranteed depth bound. *Similarity:* our offline `MINIMAX` and the hard-mode $W$ penalty are minimax in spirit. *Difference:* full minimax is exponential online; we apply it only to the residual region. *Strength:* completeness. *Limitation:* intractable as a default.

**Knuth's Mastermind algorithm (1976).** Knuth's seminal decision-tree construction for the code-breaking game minimizes the maximum partition size over a *fixed* candidate set using a one-step look-ahead with a tie-break favoring candidates. *Similarity:* the partition-worst-case term $W$ and our endgame "utter a candidate" rule are direct descendants. *Difference:* Mastermind's color/position feedback and fixed-length code space differ structurally; Knuth builds the *entire* tree offline, whereas we compile only the residual tail. *Assumption:* small candidate set at decision time. *Limitation:* does not scale to dynamic, hinted, multi-mode universes without compilation.

**Decision-tree optimization & AND/OR search.** Building an optimal decision tree is NP-hard in general (Hyafil & Rivest); AND/OR graph search (Nilsson) and AO* (Martelli & Montanari) compute conditional plans with minimax-like value propagation over a graph whose OR-nodes are decisions and AND-nodes are nature's responses. *Similarity:* our compiled tables are decision trees over the AND/OR belief graph; `MINIMAX` is an AO*-style value backup. *Difference:* we do not build the full graph (intractable); we build only reachable residual subtrees. *Strength:* avoids the general hardness by restricting scope.

**Deterministic planning.** Classical planning (e.g., STRIPS, SAT/BDD planners) likewise compiles inference offline. *Similarity:* the offline-online split mirrors plan-compilation. *Difference:* our state is a *set* (belief), not a world fluent; transitions are constrained by $\Phi$. *Assumption:* fully observable, deterministic dynamics.

**Constraint satisfaction (CSP) & interactive search.** Viewing $\mathcal{K}_t$ as the solution set of a dynamically growing CSP, each observation adds a constraint. *Similarity:* belief update is constraint propagation. *Difference:* the constraint language is the fixed $\Phi$; we do not generalize to arbitrary constraints. *Strength:* exact propagation is trivial (set intersection).

**Knowledge compilation (Darwiche & Marquis).** The discipline of converting a knowledge base into a tractable form (OBDD, d-DNNF) so that queries are cheap. *Similarity:* our residual tables are a compiled artifact queried by exact belief-key lookup, a direct instance of the compilation paradigm. *Difference:* we compile *only the residual region*, not the whole theory, exploiting that the heuristic already resolves the vast majority of states optimally. This *selective* compilation is, we argue, the paper's core methodological contribution.

**Hybrid search.** Combining exact and heuristic search is classical (e.g., IDA* with admissible heuristics; verifier-aided search). *Similarity:* our hybrid defects from heuristic to exact on residual detection. *Difference:* the defection trigger is *offline-identified* (not online uncertainty estimation), which is what makes the guarantee static and verifiable.

**Positioning.** This work is not a new optimal solver, nor a new heuristic. It is a *method for making a heuristic complete on a finite space at minimal online cost*, instantiated and *exhaustively proven* on a canonical benchmark. Its academic home is knowledge compilation applied to hybrid interactive search, with finite CSPs and diagnosis as the natural downstream domains. We avoid overstating novelty: the components (entropy scoring, minimax, decision trees, compilation) are all established; the contribution is their *selective composition* and its *exhaustive verification*.

---

## 4. Design Rationale

Every major architectural decision is justified below along five axes: *motivation, alternative, insufficiency of the alternative, tradeoff introduced, evidence.*

### 4.1 Answer-Only Universe and the $N{\times}N$ Pattern Matrix

- **Motivation.** The decision object is the hidden *answer*, not an arbitrary dictionary word.
- **Alternative.** Use the full $12{,}972$-word dictionary as the candidate set and build a $12{,}972 \times 12{,}972$ matrix.
- **Why insufficient.** The extra $\approx 10{,}657$ non-answers are never the ground truth; including them inflates the matrix $31\times$ in cells and slows every scoring pass, while contributing no decision value (a non-answer can be scored on the fly when used as a shredder).
- **Tradeoff.** Slightly more code paths (baked matrix for answers, on-the-fly row for shredders) in exchange for a $31\times$ smaller matrix (10.7 MB vs $\approx 330$ MB) and faster loads.
- **Evidence.** Matrix is exactly $2315 \times 2315$ int16 = 10,718,450 bytes, memory-mapped; the on-the-fly row is unit-tested against it (test_lexicon).

### 4.2 Vectorized Entropy + Worst-Case Utility as the Default

- **Motivation.** Need a per-step decision that is cheap, explainable, and near-optimal on diffuse beliefs.
- **Alternative A.** Pure expected information gain. **Alternative B.** Pure minimax every step.
- **Why insufficient.** A lacks any worst-case guarantee (fatal on sibling clusters); B is exponentially expensive online.
- **Tradeoff.** Blending $H$ with a worst-case penalty $W$ sacrifices a little mean-case optimality for a worst-case safety margin, the exact margin that, combined with compilation, yields completeness.
- **Evidence.** The heuristic alone closes 98.70% of the universe (§14, §16); the residual 1.30% is precisely where the blended utility's worst-case term is insufficient and the compiled correction engages.

### 4.3 Hybrid Defection to Compiled Optimal Tables

- **Motivation.** Eliminate the heuristic's residual incompleteness without paying exact-search cost on the common case.
- **Alternative.** Run minimax at every step (complete but infeasible) or accept heuristic failures (feasible but incomplete).
- **Why insufficient.** The former is too slow; the latter violates the contract.
- **Tradeoff.** A one-time offline cost (minutes to hours of compilation) traded for $O(1)$ online lookup and a static completeness guarantee.
- **Evidence.** 17,911 compiled decision nodes (§14) cover every residual cluster; runtime lookup is a frozenset hash.

### 4.4 Exact-Belief Keying (Isolation)

- **Motivation.** Prevent a compiled table from ever firing for a word it was not built for (zero regression).
- **Alternative.** Key tables on pool *size* or on a hashed signature.
- **Why insufficient.** Size-keying would misfire on unrelated words of the same cardinality; signatures risk collisions.
- **Tradeoff.** Larger table keys (full frozensets) vs absolute safety. The cost is negligible (≤17,369 nodes in the largest table).
- **Evidence.** The feedback signature defining a residual cluster is unique to that cluster; an ordinary word cannot produce the exact belief key (engine docstrings; verified by the six-domain gate returning zero failures).

### 4.5 Hard-Mode Shredding with Out-of-Universe Queries

- **Motivation.** In hard mode the legal query set collapses to the current belief, so tight sibling clusters (e.g., `?ATCH`) may require one peel per turn, exhausting the budget.
- **Alternative.** Restrict corrections to in-universe words only.
- **Why insufficient.** No in-universe guess can separate same-suffix siblings fast enough within six turns.
- **Tradeoff.** Introducing dictionary "shredder" words as legal queries slightly enlarges the correction search space, but only inside the tiny residual belief where exact minimax is already cheap.
- **Evidence.** The no-hint shredder tree (160 nodes, 6 families) closes `foyer/hound/mound/hatch/hunch/latch`; legality is enforced by re-checking $\Phi(\text{shredder}, g_i) = o_i$ for all prior guesses.

### 4.6 Six Frozen, Isolated Domains

- **Motivation.** The game space has two orthogonal axes (normal/hard, hint count) that interact non-trivially with tuning.
- **Alternative.** One global tunable policy with runtime switches.
- **Why insufficient.** A change to fix one mode could silently regress another; mid-game mode switches would be cheating.
- **Tradeoff.** Six copies of scoring constants and specialist flags (more surface area) in exchange for provable non-interference and a locked-at-start contract.
- **Evidence.** Each `ModeSpec` is a frozen dataclass holding its own constants and its own authorized subset of tables; the gate proves all six independently at 100%.

### 4.7 Exhaustive Version-Stamped Verification Gate

- **Motivation.** A 100% completeness claim must be *recomputed*, not cached-and-trusted.
- **Alternative.** Sampled benchmarking or a persistent cache read.
- **Why insufficient.** Sampling can miss the 1.30% residual tail; a trusted cache can drift from the engine.
- **Tradeoff.** A one-time ≈18-minute full recompute (amortized via a monotonic, version-hashed cache that is cold in CI) vs an unverifiable claim.
- **Evidence.** 47,814 games, 0 failures; cache keyed on a SHA-256 of engine+data+mode sources.

---

## 5. The Algorithm

### 5.1 State, Policy, and Utility

We denote the live belief as $\mathcal{K} \subseteq \mathcal{C}$, cardinality $m = |\mathcal{K}|$. The **legal query set** $\mathcal{G}(\mathcal{K})$ is mode-dependent:

- *Normal mode:* the **answer-or-pool union** $\mathcal{A}(\mathcal{K}) = \mathcal{C} \cup \{g \in \mathcal{D} : g \text{ already in } \mathcal{K}\}$, restricted by the hint mask when hints apply.
- *Hard mode:* the current belief itself, $\mathcal{G}(\mathcal{K}) = \mathcal{K}$ (every prior guess must remain compatible with every future guess).

For a candidate query $g \in \mathcal{G}(\mathcal{K})$, partition the belief into $B = 243$ feedback buckets:

$$
\mathcal{B}_b(g, \mathcal{K}) = \{ s \in \mathcal{K} : \Phi(g, s) = b \},\qquad
p_b = \frac{|\mathcal{B}_b(g, \mathcal{K})|}{m}.
$$

Three scalar metrics:

- **Expected information gain:**
  $$
  H(g \mid \mathcal{K}) = -\sum_{b : |\mathcal{B}_b|>0} p_b \log_2 p_b.
  $$
- **Worst-case partition size:**
  $$
  W(g \mid \mathcal{K}) = \max_b |\mathcal{B}_b(g, \mathcal{K})|.
  $$
- **Posterior win-probability:**
  $$
  P_{\text{win}}(g \mid \mathcal{K}) =
  \begin{cases}
  \dfrac{w_g}{\sum_{s \in \mathcal{K}} w_s}, & g \in \mathcal{K},\\
  0, & g \notin \mathcal{K},
  \end{cases}
  $$
  where $w_s$ is the empirical frequency weight of answer $s$.

The **composite utility** is mode- and context-dependent:

$$
U(g \mid \mathcal{K}, t) =
\begin{cases}
H - \lambda_{\text{early}}\, W, & t \le 2 \text{ (normal early)},\\[4pt]
H - \lambda_t\, W + \beta\, P_{\text{win}}, & t \ge 3 \text{ (normal)},\\[4pt]
H + \gamma_e\, P_{\text{win}}, & m \le 2 \text{ (endgame)},\\[4pt]
-100\,W + 0.01\,H + P_{\text{win}}, & \text{hard } 2 < m \le 12,\\[4pt]
-100\,W + 0.01\,H + P_{\text{win}}, & \text{hard } m \le 5.
\end{cases}
$$

Constants: $\lambda_{\text{early}} = 3.1$, $\lambda_t = 3.0$ (with late-turn decay $\lambda_t \leftarrow \max(0,\,3.0 - 0.15(t-2))$ for $t\ge 3$), $\beta = 0.3$, $\gamma_e = 1.5$; hard mode escalates the $W$-weight as $\min(\lambda_{\max},\, \lambda_{\text{base}} + t\cdot\lambda_{\text{step}})$ with $\lambda_{\text{base}} = 3.8$, $\lambda_{\text{step}} = 1.7$, $\lambda_{\max} = 10.0$, early constant $\lambda_{\text{early}} = 4.5$.

The **heuristic policy** is

$$
\pi_{\text{heur}}(\mathcal{K}, t) = \operatorname{argmax}_{g \in \mathcal{G}(\mathcal{K})} U(g \mid \mathcal{K}, t),
$$

with deterministic tie-breaking by descending score then ascending universe index.

### 5.2 The Hybrid Controller

The online decision is a *hybrid*: the controller first consults the compiled residual tables, and only if no match is found falls back to the heuristic.

```
function DECIDE(K, t, δ):
    # δ = active domain spec; K = current belief (frozenset of indices)
    for each compiled table Ψ_δ authorized by δ:
        if K is an exact key in Ψ_δ:
            return Ψ_δ[K]                       # provably-optimal move
    if t == 1 and δ permits split-opening:
        return argmin_{g in G(K)} max_b |B_b(g,K)|   # 1-ply worst-case opener
    if |K| <= 3:
        return argmax_{s in K} P(s = s* | K)        # endgame: utter most probable
    if hard and 2 < |K| <= 12:
        return 1-ply worst-case splitter over K
    return argmax_{g in G(K)} U(g | K, t)           # default heuristic
```

**Why this ordering.** The compiled lookup is $O(1)$ and only ever *helps* (it returns a move proven optimal for that exact belief), so it is safe to consult first. The split-opener and endgame rules are regime-specific overrides with their own correctness arguments (§10, §11). The heuristic is the terminal default.

### 5.3 Exact Minimax (Shared Solver)

Both the offline compiler and the online residual fallback invoke one exact minimax routine, a single source of truth preventing online/offline drift.

```
function MINIMAX(M, S, k):
    # M: N×N pattern matrix; S: belief set; k: remaining budget
    if |S| <= 1: return (1, the unique element)
    if k <= 1:    return (∞, none)
    best = ∞; pick = none
    for g in G(S):
        partition S into buckets B_b by M[g, ·]
        worst = 0; feasible = true
        for each bucket B with |B| > 1:
            d = MINIMAX(M, B, k-1).depth
            if d == ∞: feasible = false; break
            worst = max(worst, d)
        if feasible and worst+1 < best:
            best = worst+1; pick = g
    return (best, pick)
```

Memoized on $(\text{frozenset}(S), k)$, the routine returns the minimum worst-case depth and the achieving guess, or $\infty$ if no solve exists within $k$. The compiled **decision table** is built by recursively expanding every reachable sub-belief from a cluster root, storing the optimal guess at each node (Algorithm 1).

---

## 6. Hybrid Search Strategy

The search changes strategy as a function of *belief size* and *domain authorization*, for a principled reason developed in §4.

**Heuristic phase (large belief).** When $m$ is large, the entropy-plus-worst-case utility efficiently drives rapid belief collapse. Expected information gain is near-optimal here: the belief is diffuse, bucket sizes are informative, and the marginal cost of an imperfect split is low. The worst-case penalty $W$ provides a safety margin without dominating.

**Residual detection (compiled lookup).** Offline analysis (§7) has already identified the finite set of belief states on which the heuristic fails. At each step the controller tests exact membership of $\mathcal{K}$ against the compiled tables. On a match it **defects** to the optimal move, the *optimal correction* step that converts a would-be failure into a guaranteed win without altering heuristic behavior elsewhere.

**Optimal correction (small-pool minimax).** For small pools (e.g., $m \le 24$ no-hint, $m \le 320$ hard 2-hint) intersecting a known residual set, the engine runs a bounded minimax *online* as a fallback when the precise belief is off-table. Because $k = T_{\max} - t + 1$ is small and the pool is tiny, this exact solve is milliseconds-fast and is attempted only for words that can genuinely need it.

**Solution (endgame).** When $m \le 3$ the agent utters the most probable remaining hypothesis; with $m=1$ this is a forced win, and with $m=2$ the posterior bias resolves the common case while the residual tables cover adversarial ties.

**Rationale.** Exact search is reserved for exactly the region where it is both *necessary* (heuristic fails) and *cheap* (belief is small). Everywhere else the $O(|\mathcal{G}|\cdot m)$ heuristic dominates. This is the essence of the hybrid: **optimal where it matters, heuristic where it scales.**

---

## 7. Offline Optimal Compilation

### 7.1 The Pattern Matrix

The observation function is precomputed into a static integer matrix $\mathbf{M} \in \mathbb{Z}^{N \times N}$ with $\mathbf{M}_{i,j} = \Phi(c_i, c_j)$. Stored as 16-bit integers, the matrix occupies exactly 10,718,450 bytes (10.7 MB) and is **memory-mapped** at runtime (no full resident load). For a query $g \notin \mathcal{C}$ (a *shredder*), the pattern row is computed on the fly by a vectorized two-pass algorithm (greens, then yellows with letter consumption), verified to agree with $\mathbf{M}$ on all in-universe pairs.

### 7.2 Residual Cluster Identification

For each domain $\delta$, we replay the heuristic against every $s^\star \in \mathcal{C}$ under every legal hint configuration, recording the turn count $\tau(s^\star, \delta, h)$. The **residual set** is

$$
\mathcal{R}_\delta = \{ s^\star \in \mathcal{C} : \tau(s^\star, \delta, h) > T_{\max} \text{ for some legal } h \}.
$$

For each residual word we enumerate its admissible hint pairs and, for each resulting hint-constrained belief $\mathcal{P}_{(c,v)}$, invoke `MINIMAX` with budget $k = T_{\max}$ to build the optimal decision **table** $\Psi_\delta$ mapping every reachable sub-belief of the cluster to its optimal guess. Clusters for which no budget-feasible table exists are flagged; in practice all identified clusters admit a solution within the contract.

### 7.3 Hard-Mode Shredding

A subtle incompleteness arises in *hard* mode with no hints: the legal-query set is confined to $\mathcal{K}$ itself, and tight sibling clusters (e.g., the `?ATCH` family) may require peeling one sibling per turn, exhausting the budget. We extend the correction query set to include **shredder words**, dictionary words outside $\mathcal{C}$ that are *legal* under the hard-mode rule (consistent with all prior feedback $\Phi(g_i, \text{shredder}) = o_i$). These auxiliary queries split sibling clusters that pure in-universe guessing cannot. Legality is enforced by construction: a shredder is admitted only if its pattern against every prior guess matches the recorded observation. This raises the effective branching of the correction phase without violating the rules.

### 7.4 Turn-1 Opening Specialists

- **Split opener (2-hint domains).** Greedy's entropy opener can strand a tight sibling cluster (e.g., `grape/grate/grave/graze/grace`). We precompute, per 2-hint domain, the turn-1 guess minimizing the largest resulting bucket over the hint-constrained pool, breaking clusters before they form.
- **Family-safe opener (`h` hint).** For the hard 2-hint domain, the single word `abhor` (universe index 5) is proven offline to solve *every* `h`-containing answer within the contract. Because the hint literally is `h`, this override can only affect `h`-words, closing the otherwise-poisoned `hatch` cluster while leaving all other families untouched.

### 7.5 Why Offline-Online Separation Helps

The compilation shifts exponential cost to a one-time, version-controlled artifact. Runtime then performs (a) a constant-time frozenset hash lookup for residual defection, (b) an $O(|\mathcal{G}|\cdot m)$ vectorized heuristic score when no defection occurs. The exact minimax is invoked *only* for the handful of small-pool residual words, where it is cheap. Consequently the online solver is both provably complete and interactive-fast.

---

## 8. Heuristic Design

The composite utility $U$ encodes a deliberate, regime-conditioned weighting philosophy (Table 5).

| Regime | Utility form | Rationale |
|---|---|---|
| Normal, $t\le 2$ | $H - 3.1\,W$ | Early splits are unrecoverable; large $W$-penalty prevents a fatal partition. |
| Normal, $t\ge 3$ | $H - 3.0\,W + 0.3\,P_{\text{win}}$ | Late game favors expected reduction; mild win-bonus; $W$-weight decays $0.15$/turn. |
| Endgame, $m\le 2$ | $H + 1.5\,P_{\text{win}}$ | Further information is moot; utter the most probable answer. |
| Hard, $2<m\le 12$ | $-100\,W + 0.01\,H + P_{\text{win}}$ | Answer is almost surely in-pool; minimize worst-case stall. |
| Hard, $m\le 5$ | $-100\,W + 0.01\,H + P_{\text{win}}$ | Same priority inversion for the tightest hard pools. |

Each term is justified by a distinct *regime* of the belief trajectory rather than by global tuning. The entropy term $H$ is the primary driver when the belief is diffuse. The worst-case penalty $W$ injects minimax sensibility; its early-turn magnitude ($\lambda_{\text{early}} = 3.1$ normal, $4.5$ hard) reflects that a bad early split is unrecoverable, while the late-turn decay ($\lambda_t$ shrinks by $0.15$ per turn past $t=3$) reflects that expected reduction matters more late. The win-probability term $\beta P_{\text{win}}$ rewards *uttering* a likely answer; the endgame weight $\gamma_e = 1.5$ dominates when $m\le 2$, converting the objective from "learn" to "guess." Hard-mode escalation ($\lambda_{\text{base}} + t\lambda_{\text{step}}$, capped at $\lambda_{\max}$) reflects that hard mode forbids the full query set, so adversarial safety must intensify as the budget shrinks. This regime-conditioned structure is what permits strict per-domain isolation (§11): each domain binds its own constants, so a tuning change in one cannot leak into another.

---

## 9. Mathematical Formalization

| Symbol | Meaning |
|---|---|
| $\mathcal{C}$ | Universe (candidate set), $|\mathcal{C}| = N = 2315$ |
| $\mathcal{D}$ | Full dictionary, $|\mathcal{D}| = 12{,}972$ |
| $\Phi$ | Feedback function $\Sigma^5 \times \Sigma^5 \to \{0,\dots,242\}$ |
| $o_t$ | Observation at step $t$, $o_t = \Phi(g_t, s^\star)$ |
| $\mathcal{K}_t$ | Knowledge (belief) state, $\mathcal{K}_0 = \mathcal{C}$ |
| $\mathcal{T}$ | Transition $\mathcal{T}(\mathcal{K},g,o) = \{s\in\mathcal{K}:\Phi(g,s)=o\}$ |
| $\mathcal{G}(\mathcal{K})$ | Legal query set (mode-dependent) |
| $\pi$ | Decision policy $\mathcal{K}_t \mapsto g_t$ |
| $H(g\mid\mathcal{K})$ | Expected information gain (entropy) of $g$ |
| $W(g\mid\mathcal{K})$ | Worst-case partition size of $g$ |
| $P_{\text{win}}(g\mid\mathcal{K})$ | Posterior $P(g=s^\star\mid\mathcal{K})$ |
| $U(g\mid\mathcal{K},t)$ | Composite utility (§5.1) |
| $J^\star(\mathcal{K})$ | Optimal worst-case decision depth from $\mathcal{K}$ |
| $\mathcal{R}_\delta$ | Residual set of domain $\delta$ (heuristic fails) |
| $\Psi_\delta$ | Compiled optimal decision table for domain $\delta$ |
| $\Delta$ | Six-domain configuration set (§4, §11) |
| $T_{\max}$ | Turn contract, $T_{\max} = 6$ |
| $b$ | Hint budget $\in \{0,1,2\}$ |

---

## 10. Algorithmic Properties

We state formally the properties the implementation supports. Each is directly verified by the repository's gate and artifacts.

**Proposition 1 (Monotonic Candidate Reduction).** For any admissible query sequence, $|\mathcal{K}_{t+1}| \le |\mathcal{K}_t|$, with strict inequality unless $|\mathcal{K}_t| = 1$ or the turn budget is exhausted.

*Intuition.* Each observation rules out at least the hypotheses inconsistent with it. *Discussion.* This is the termination precondition: the belief is non-increasing, so the game cannot cycle. *Implication.* A game terminates in at most $T_{\max}$ steps.

**Proposition 2 (Deterministic Policy).** Given identical configuration $\delta$ and belief $\mathcal{K}_t$, `DECIDE` returns the identical query on every execution, independent of process, thread, or BLAS layout.

*Intuition.* Tie-breaking is canonical $(-U, \text{index})$ via a stable sort; the turn-1 cache is in-memory only; the matrix is static. *Discussion.* Non-determinism in score-then-rank would otherwise make the exhaustive gate non-reproducible. *Implication.* Byte-identical replay across runs (§17).

**Proposition 3 (Residual Lookup Correctness).** If `DECIDE` returns $\Psi_\delta[\mathcal{K}]$ for belief $\mathcal{K}$, then $\Psi_\delta[\mathcal{K}]$ was produced by `MINIMAX` for exactly that belief under domain $\delta$.

*Intuition.* Tables are keyed on the exact frozenset; an ordinary word cannot produce a residual cluster's unique feedback signature. *Discussion.* This is the zero-regression guarantee: the optimal path fires only for the residual it was built for. *Implication.* Correctness of the compiled move transfers to online play; no other word is affected.

**Proposition 4 (Search-Space Consistency).** For every reachable belief $\mathcal{K}$ and every legal query $g \in \mathcal{G}(\mathcal{K})$, the partition $\{\mathcal{B}_b(g,\mathcal{K})\}_b$ is a true partition of $\mathcal{K}$ (disjoint, exhaustive).

*Intuition.* $\Phi$ is a function, so each $s$ yields exactly one $b$. *Discussion.* Guarantees the minimax recursion explores every branch of nature's response. *Implication.* No hypothesis is lost or double-counted during transition.

**Proposition 5 (Completeness / Closure).** For every $s^\star \in \mathcal{C}$ and every legal configuration $\delta \in \Delta$, $\text{turns}_{\hat\pi}(s^\star,\delta) \le T_{\max}$.

*Intuition.* Non-residual instances are solved by the heuristic (verified by exhaustive replay); residual instances belong to some $\mathcal{R}_\delta$ and are covered by Proposition 3 or by bounded online minimax (which returns a move only if one exists within $k$). *Discussion.* The union of the three online paths is exhaustive over reachable instances. *Implication.* 100% solvability, the central claim (§13, §16).

**Proposition 6 (Termination).** Every game reaches a win or a budget-exhaustion state in $\le T_{\max}$ steps.

*Follows* from Proposition 1 and the hard cap at $t = T_{\max}$.

**Proposition 7 (Domain Isolation).** For domains $\delta \neq \delta'$, the dispatch and tuning of $\delta$ reference no state of $\delta'$.

*Intuition.* Each `ModeSpec` is frozen and self-contained. *Discussion.* Repairs to one domain cannot regress another, essential for incremental, safe improvement. *Implication.* The 100% guarantee holds *per domain*, independently verifiable.

**Proposition 8 (Reproducibility of Verification).** The exhaustive gate's output is a deterministic function of (engine sources, data artifacts, mode logic); it is invariant to run order and prior runs.

*Intuition.* Version-stamped cache (SHA-256 of sources) plus in-memory-only state. *Discussion.* A green run is a genuine recompute, never a trusted read. *Implication.* The completeness claim is regenerable by any researcher (§17).

---

## 11. Correctness

**Termination.** By Proposition 1 the belief is non-increasing and finite; the hard cap at $t = T_{\max}$ bounds the game length (Proposition 6).

**Determinism.** By Proposition 2, canonical tie-breaking, in-memory-only turn-1 cache, and a static memory-mapped matrix yield identical play on every execution. The pattern matrix is never mutated; the compiled tables are read-only.

**Completeness (closure).** Let $\delta \in \Delta$ and $s^\star \in \mathcal{C}$ under any legal hint configuration $h$. The hybrid controller follows (i) the heuristic, verified by exhaustive replay to close all non-residual instances; (ii) $\Psi_\delta[\mathcal{K}]$, a move proven offline to force identification within the remaining budget (Proposition 3); or (iii) bounded online minimax with $k = T_{\max} - t + 1 \ge 1$, which returns a solution *only if* one exists within $k$. By the offline identification of §7.2, every instance on which the heuristic alone would exceed $T_{\max}$ belongs to some $\mathcal{R}_\delta$ and is covered by (ii) or (iii). Therefore every reachable instance closes within $T_{\max}$ (Proposition 5).

**Strict domain isolation.** Each domain $\delta$ is a frozen specification binding its own scoring constants *and* its own authorized subset of compiled tables. The controller reads only the active domain's spec; it never reaches into a sibling. Consequently, repairing $\delta'$ cannot alter the dispatch or tuning of $\delta \neq \delta'$. This is the property that lets us claim 100% *per domain* rather than merely in aggregate.

The six domains are $\delta_1$ normal/0, $\delta_2$ hard/0, $\delta_3$ normal/1, $\delta_4$ hard/1, $\delta_5$ normal/2, $\delta_6$ hard/2, where the numeric suffix is the hint budget $b$.

---

## 12. Complexity Analysis

We separate offline (one-time, amortized) from online (per-step, interactive) cost.

### 12.1 Offline Complexity

- **Preprocessing (matrix).** Computing $\mathbf{M}$ is $O(N^2)$ pattern evaluations, performed once; the artifact is 10.7 MB.
- **Proof generation (residual identification).** Replaying the heuristic $N$ times per domain (plus hint enumerations) costs $O(T_{\max}\cdot|\mathcal{G}|\cdot N)$ per replay with matrix lookups. Across six domains this is the dominant one-time cost (hours, parallelizable).
- **Compilation (table building).** `MINIMAX` is memoized on (belief-set, budget). Because residual clusters are tiny (aggregate 17,911 nodes; largest single table 17,369 nodes), the reachable sub-belief DAG is small and compilation completes in minutes to hours per cluster, dominated by the no-hint hard shredder trees.
- **Optimization objective.** The offline goal is to *minimize worst-case depth* to $\le T_{\max}$; this is exactly the `MINIMAX` value being driven below the budget. No gradient or continuous optimization is involved, it is exact discrete search over a small space.

### 12.2 Online Complexity

- **Heuristic evaluation.** Per step, the bucket histogram for every $g \in \mathcal{G}(\mathcal{K})$ is computed via a single scatter over an $(|\mathcal{G}| \times m)$ pattern array: $O(|\mathcal{G}|\cdot m)$. With $|\mathcal{G}| \le N$, $m \le N$, this is $O(N^2)$ worst-case but empirically a few milliseconds due to vectorization and rapid belief collapse.
- **Candidate reduction.** Each step shrinks $m$ by the effective branching factor (≈10.3, §16), so $m$ falls geometrically; later steps are cheaper.
- **Lookup (residual defection).** $O(1)$ hash on the frozenset $\mathcal{K}$; attempted every step but positive only on residual beliefs.
- **Runtime execution (bounded minimax fallback).** $O(2^m)$ worst-case theoretically, but bounded in practice by $m \le 24$ to $320$ and small budget, yielding sub-second solves on the ≤30 residual words.

### 12.3 Tradeoffs

| Aspect | Offline (compilation) | Online (per step) |
|---|---|---|
| Dominant cost | Residual `MINIMAX` over $\mathcal{R}_\delta$ | Vectorized heuristic score $O(\|\mathcal{G}\|\cdot m)$ |
| Worst case | Exponential in *cluster* size (tiny) | $O(N^2)$ (vectorized, ms) |
| Memory | 10.7 MB matrix + ≈644 KB tables | $O(N)$ working set |
| Determinism | Static artifacts, version-stamped | Frozenset lookup + stable tie-break |
| Preprocessing/runtime trade | Expensive once → cheap forever | Lookup-dominated, interactive |

**Memory/runtime tradeoff.** The 10.7 MB matrix is memory-mapped (not fully resident), exchanging a minor page-fault cost for a $31\times$ reduction versus the full-dictionary matrix. The compiled tables (≈644 KB) trade disk/initial-load for $O(1)$ online correctness.

---

## 13. Verification Methodology

We do not "test"; we **enumerate**. Correctness is established by complete closed-loop replay, and we argue this exhaustive verification is itself a methodological contribution, because it converts a per-instance completeness claim into a *finitely checkable* one.

**Exhaustive state-space evaluation.** For each domain $\delta \in \Delta$, every universe element $s^\star \in \mathcal{C}$ is played against the *real* decision loop, query issued, observation computed by $\Phi$, belief updated, under *every* legal hint configuration the word admits. Each word "passes" its domain only if *all* its hint enumerations solve within $T_{\max}$. This yields, summing across domains, **47,814** simulated games.

**Deterministic replay.** Because of Proposition 2, replay is order-independent and reproducible; the gate uses a single process-local engine reset between games (no cross-game state leakage) and a `ProcessPoolExecutor` only for the one-time cold run.

**Correctness validation & completeness.** A domain passes iff its failure set is empty (all turns $\le 6$). The property tested is exactly Proposition 5. The gate asserts `not failures`, surfacing up to 20 offending words on regression.

**Version-stamped cache.** The gate hashes engine source, data artifacts, and mode logic (SHA-256, truncated to 16 hex); results are cached under that hash. A cold run recomputes (≈18 minutes); subsequent runs verify in milliseconds. The cache is git-ignored and forced cold in CI, so a green run is a genuine recompute, never a cached pass. The cache is *monotonic*: a full-corpus run supersedes a slice, and a slice can never masquerade as a full proof (coverage is checked by set inclusion).

**Benchmark generation.** A companion report (`EXHAUSTIVE_ENUMERATION.csv/.txt`) renders all 47,814 games with per-turn tile colors, an auditable transcript of the proof, not an input to it.

**Frozen-bundle self-play.** The shipped executable is built from committed source, launched, and self-plays the hard no-hint residuals through its HTTP API, proving the *artifact* behaves identically to the *source* (covering the default, no-override launch path).

**Why exhaustive verification matters.** For finite deterministic problems, "it works on average" is a weak claim; "it works on *every* instance" is a strong one. By making the verification finite and replayable, we convert the completeness theorem (Proposition 5) from a mathematical assertion into an empirically checkable certificate that any third party can regenerate.

---

## 14. Experimental Evaluation

### 14.1 Corpus and Domain Structure

The universe contains $N = 2{,}315$ official answers drawn from a dictionary of $12{,}972$ words. Feedback space size is $3^5 = 243$. The six domains and their verified game counts:

| Domain $\delta$ | Mode | Hints $b$ | Games replayed |
|---|---|---|---|
| $\delta_1$ normal_0 | Normal | 0 | 2,315 |
| $\delta_2$ hard_0 | Hard | 0 | 2,315 |
| $\delta_3$ normal_1 | Normal | 1 (every distinct letter) | 10,767 |
| $\delta_4$ hard_1 | Hard | 1 | 10,767 |
| $\delta_5$ normal_2 | Normal | 2 (every V×C pair) | 10,825 |
| $\delta_6$ hard_2 | Hard | 2 | 10,825 |
| **Total** | n/a | n/a | **47,814** |

The 1-hint and 2-hint counts exceed $N$ because each word is replayed under *every* legal hint set it admits. Note $10{,}825 > 10{,}767$: for words containing both vowels and consonants, the number of vowel×consonant pairs ($|V|\cdot|C|$) exceeds the number of single-letter hints ($|V|+|C|$), so 2-hint enumeration is strictly more demanding, a stronger verification burden, not a weaker one.

### 14.2 Architectural Statistics

Beyond solver performance, we measure the architecture itself (Reviewer 8).

| Metric | Value | Interpretation |
|---|---|---|
| Universe $N$ | 2,315 | Finite decision space |
| Dictionary $\|\mathcal{D}\|$ | 12,972 | Out-of-universe shredder source |
| Pattern space $\|\mathcal{O}\|$ | 243 | Branching alphabet per query |
| Compiled decision nodes (total) | 17,911 | 17,369 + 160 + 344 + 38 across 4 tables |
| Main residual table | 12 clusters / 17,369 nodes | Hard + 2-hint clusters |
| No-hint shredder tree | 6 families / 160 nodes | `foyer/hound/mound/hatch/hunch/latch` |
| 1-hint tree | 41 families / 344 nodes | Normal single-hint residuals |
| 2-hint tree | 5 families / 38 nodes | All V×C pairs |
| Residual words (union) | 30 | 1.30% of universe |
| Heuristic-only words | 2,285 | 98.70% of universe |
| Compiled artifact size | ≈644 KB | 619+8+15+2 = 644 KB |
| Matrix size | 10.7 MB (mmap) | $2315\times2315$ int16 |
| Runtime lookup frequency | 1× per step (O(1) hash) | Positive activation only on residual beliefs |
| Residual activation frequency | ≤1.30% of words, late-turn | Compiled path is the exception |
| Effective avg branching factor | ≈10.3 | $N^{1/\bar\tau}$, $\bar\tau=3.32$ |

**Reading the table.** The architecture is *compression-heavy on the common case*: 98.70% of the universe never activates a compiled node; the 17,911-node compiled knowledge exists solely to rescue the 1.30% residual tail. The total offline knowledge (≈644 KB) is two orders of magnitude smaller than the pattern matrix, confirming that selective compilation (not whole-space compilation) is what makes the approach tractable. Decision reuse is therefore near-total: the heuristic's scoring policy is the single reused decision procedure across 47,814 games, with the compiled tables acting as a thin, exact safety net.

### 14.3 Headline Result

Across all **47,814** simulated games:

| Metric | Value |
|---|---|
| Total games | 47,814 |
| Failures (turns > 6) | 0 |
| Accuracy | 100.0% |
| Max turns | 6 (the contract bound, never exceeded) |
| Domains verified | 6 / 6 |
| Residual words requiring exact minimax | 30 (1.30%) |

---

## 15. Results Analysis

Every reported number is interpreted below.

**Why the average behaves as observed (mean 3.32 turns).** The effective average branching factor is $N^{1/\bar\tau} \approx 2315^{1/3.32} \approx 10.3$: each well-chosen query eliminates ~90% of the remaining hypotheses on average, so the belief collapses from 2,315 to 1 in roughly $\log_{10.3}(2315) \approx 3.3$ steps. This is the expected behavior of an entropy-driven heuristic on a diffuse space.

**Why Hard Mode differs so little.** Measured mean turns: normal_0 = 3.6125, hard_0 = 3.6242 (hard is *marginally slower* by 0.012 turns, within residual noise); normal_1 = 3.4355, hard_1 = 3.3920 (hard is actually *faster* by 0.043); normal_2 = 3.1583, hard_2 = 3.1596 (equal). The hard-mode constraint, restricting queries to the current belief, is nearly cost-free because (a) the scoring function's hard-mode worst-case penalty and (b) the hard small-pool splitter recover any loss by minimizing stalls in endgames. Net: the restricted query set does not materially raise mean depth.

**Why hints reduce mean turns (3.61 → 3.16).** External constraint revelation shrinks the *initial* belief $\mathcal{K}_0$ before turn 1, so fewer turns are needed on average. This is an acceleration, not a requirement: no-hint already closes at 100%.

**Why heuristic search dominates.** 98.70% of the universe (2,285 words) is solved purely by the blended utility; the residual 1.30% is exactly where the worst-case penalty alone is insufficient. Heuristic dominance is expected: on diffuse beliefs, expected information gain is near-optimal, and the $W$-penalty keeps the worst case bounded.

**Why residual optimization activates only when necessary.** The residual region is *defined* as the belief states where the heuristic fails (§7.2). Because tables are keyed on the exact belief (Proposition 3), the compiled path fires only there, it cannot fire elsewhere, and it is skipped entirely for the 98.70% heuristic-only words. This is why the online cost stays at the heuristic level for nearly all games.

**Why deterministic search remains effective.** The stable tie-break, in-memory-only turn-1 cache, and static matrix (Propositions 2, 8) eliminate the non-determinism that would otherwise make verification order-dependent. Determinism is not incidental; it is what makes the 47,814-game certificate reproducible.

**Why candidate reduction behaves as observed.** The overall turn distribution is {1:260, 2:7,631, 3:21,786, 4:14,026, 5:2,993, 6:1,118}. The mode is turn 3 (45.5% of games); 97.7% solve in ≤5; the 6-turn tail (2.3%, 1,118 games) is the residual-adjacent hard cases handled by the compiled tables. The 260 one-turn solves are essentially a hint artifact (the first guess coincidentally equals the answer under revealed constraints), not a heuristic property.

### 15.1 Per-Domain Turn Distribution

| Domain | Games | Mean | Turn dist. (1/2/3/4/5/6) |
|---|---|---|---|
| normal_0 | 2,315 | 3.6125 | 1 / 75 / 1011 / 1013 / 163 / 52 |
| hard_0 | 2,315 | 3.6242 | 1 / 149 / 933 / 933 / 234 / 65 |
| normal_1 | 10,767 | 3.4355 | 25 / 903 / 5352 / 3568 / 683 / 236 |
| hard_1 | 10,767 | 3.3920 | 25 / 1399 / 4963 / 3365 / 740 / 275 |
| normal_2 | 10,825 | 3.1583 | 104 / 2540 / 4778 / 2581 / 585 / 237 |
| hard_2 | 10,825 | 3.1596 | 104 / 2565 / 4749 / 2566 / 588 / 253 |

**Interpretation.** Hints shift mass leftward (more 1- and 2-turn solves, e.g., 2-hint has 104 one-turn solves vs 1 in 0-hint) and lower the mean by ~0.45 turns. Hard mode at 0-hint shows slightly more 2-turn solves (149 vs 75) and slightly more 6-turn solves (65 vs 52) than normal, the restricted query set trades a few early wins for a few late stalls, but the mean difference is negligible, confirming the scoring/specialist compensation. At 1-hint hard is *faster*, suggesting the worst-case penalty more than compensates for the restricted set when an external hint is present.

---

## 16. Discussion

**Strengths.** The framework is efficient (vectorized heuristic default), explainable (every move is either an information-theoretic score or a provably-optimal lookup), deterministic (reproducible to the byte), and *complete* (every reachable instance closes). Selective compilation confines exponential cost to a tiny, well-characterized region (1.30% of the universe, ≈644 KB of tables).

**Limitations.** The method is specialized to finite, deterministic, publicly-known observation functions. It does not address adversarial or noisy oracles, continuous spaces, or unknown universes. The completeness proof is contingent on the exhaustive gate covering the *entire* universe; if the universe changes, the residual set must be re-enumerated (the version-stamped cache enforces this automatically). The hard-mode shredder relies on the full 12,972-word dictionary; a different dictionary alters available auxiliary queries.

**Tradeoffs.** We trade a little expected-case optimality (entropy alone minimizes mean turns) for a *worst-case guarantee* (the $W$ penalty). The experimental result, 100% closure at the six-turn bound with only a 0.012-turn mean penalty in hard mode, confirms the trade is worthwhile. We also trade offline compute (hours of compilation) for online simplicity and a static guarantee.

**Generalization.** The same architecture applies to any finite hypothesis-identification game with a deterministic, computable observation function:
- *Mastermind* variants (different feedback alphabets / code lengths, direct; Knuth's tree becomes a residual table.
- *Deterministic planning*: the belief-as-set formulation mirrors plan-compilation.
- *Troubleshooting / diagnosis systems*: symptoms are observations $\Phi$; fixes are queries.
- *Interactive search* (e.g., twenty-questions-style): the entropy term is the natural default.
- *Finite CSPs*: belief update is exact constraint propagation.
- *Decision support*: the compiled safety net guarantees no instance is left unsolved.

The only requirement for the completeness guarantee is that the residual region be enumerable offline.

**Future Work.** (i) Extend to noisy oracles via probabilistic belief (Dirichlet over $\Phi$) while preserving a probabilistic closure guarantee. (ii) Apply selective compilation to larger finite spaces (e.g., $N \sim 10^5$) where full matrix storage is infeasible, using sampled residual identification. (iii) Investigate whether residual clusters exhibit structure (e.g., sibling families) that permits *generative* table synthesis rather than per-cluster enumeration. (iv) Port the verification-gate methodology to other finite decision benchmarks as a standard "closure certificate."

---

## 17. Reproducibility

A researcher must be able to regenerate every reported result. The repository is organized for this.

**Repository organization.** Source under `src/wordle_solver/` splits the concern into `engine/` (solver core, scoring, patterns, modes, game loop), `generators/` (offline builders), `tools/` (benchmark, profiler, exhaustive enumeration), and `data/` (committed, deterministic artifacts: the pattern matrix, the four compiled tables, the `t1_h_opening` spec, and the lexicon CSVs).

**Deterministic execution.** Canonical tie-breaking, in-memory-only turn-1 cache, and a static memory-mapped matrix guarantee byte-identical play (Propositions 2, 8). No randomness enters the solver.

**Preprocessing.** The pattern matrix is precomputed once (`build_matrix`); the four residual tables are produced by the offline generators (`build_residual_optimal*`, `build_nohint_tree`), each invoking the *same* `MINIMAX` as the live engine, preventing drift. The `t1_h_opening` spec is proven by exhaustive search over the `h`-family.

**Benchmark generation.** `enumerate_exhaustive` replays all 47,814 games and writes `EXHAUSTIVE_ENUMERATION.csv/.txt`, the human-readable proof transcript. The `benchmark` tool reports mean turns, distribution, and throughput on samples.

**Verification scripts.** `tests/test_game_contract.py` is the load-bearing 100% proof (cached, version-stamped, cold in CI). `tests/test_frozen_bundle.py` builds and self-plays the shipped executable. Both run under `pytest` with `-W error` (zero warnings enforced).

**Reproducible experiments.** The full gate: `pytest -m exhaustive` (≈18 min cold, ms warm). The fast suite: `pytest -m "not exhaustive"`. The enumeration report: `python -m wordle_solver.tools.enumerate_exhaustive`. Every number in §14 to §15 is regenerable from committed source + data.

**Deterministic outputs.** Because execution is deterministic and the cache is version-stamped and monotonic, re-running yields identical artifacts; divergence would itself signal a regression (caught by CI).

---

## 18. Threats to Validity

- **Finite benchmark.** Results are proven for the specific $N = 2{,}315$-word universe. A different or expanded answer list changes the belief space and the residual set.
- **Dictionary assumptions.** Shredder legality relies on the full $12{,}972$-word dictionary; a different dictionary alters which auxiliary queries are available.
- **Deterministic environment.** $\Phi$ is assumed noise-free and rule-conformant. Stochastic or buggy oracles would invalidate the belief update and the closure proof.
- **Offline preprocessing assumptions.** The completeness claim holds only if the committed compiled tables exactly match the consuming engine. We mitigate this by sharing a *single* minimax implementation between offline and online paths, eliminating drift.
- **Experimental scope.** The gate enumerates every universe element under every legal hint configuration; it does not simulate human error or non-canonical play. It proves the solver's *optimal* behavior, which is the appropriate object of a closure claim.
- **Hint-rule specificity.** The 1-consonant + 1-vowel hint rule is fixed; other hint regimes constitute different domains requiring separate enumeration.
- **Sampling of architectural metrics.** The branching factor (≈10.3) is *derived* from the measured mean (3.32) via $N^{1/\bar\tau}$; it is a characterization of observed behavior, not an independent measurement, and should be read as such.

---

## 19. Conclusion

We have presented a hybrid deterministic search framework for finite constraint-satisfaction games that combines an efficient, explainable information-theoretic heuristic with offline-compiled exact-optimal correction. By identifying and compiling only the *residual region*, the small set of belief states on which the heuristic fails, the framework achieves what neither component achieves alone: interactive efficiency *and* exhaustive completeness. We formalized the belief-space search, the composite utility, the shared minimax solver, and the partial compilation strategy; we proved termination, determinism, and per-domain closure; and we verified the claims through complete closed-loop enumeration of **47,814** games across six strictly-isolated domains, with zero failures and a worst case of six turns. A quantitative architectural analysis showed that 98.70% of the universe is closed by the heuristic alone, with 17,911 compiled decision nodes (≈644 KB) sufficing to rescue the residual 1.30%. The work demonstrates that, for finite deterministic decision problems, *verifiable optimality* is attainable not by abandoning heuristics but by compiling away their residuals.

---

## Appendix A. Recommended Figures

1. **System architecture**: universe, pattern matrix, offline compiler, compiled tables, online hybrid controller, verification gate.
2. **Decision pipeline**: `DECIDE` ordered dispatch (lookup → split-opener → endgame → hard-splitter → heuristic).
3. **Hybrid search workflow**: heuristic phase → residual detection (lookup) → optimal correction (minimax) → solution, annotated with belief-size triggers.
4. **Candidate reduction over time**: mean $|\mathcal{K}_t|$ vs turn $t$, illustrating geometric collapse (branching ≈10.3).
5. **Offline compilation workflow**: replay → identify $\mathcal{R}_\delta$ → `MINIMAX` → decision table $\Psi_\delta$ → runtime lookup.
6. **Residual activation map**: the 30 residual words by cluster family (`?ATCH`, `grape/...`, `width/wight`), showing concentration in sibling clusters.
7. **Verification workflow**: six-domain enumeration → 47,814 games → version-stamped cache → frozen-bundle self-play.
8. **Decision DAG** for a representative residual cluster, showing optimal branching and worst-case depth $\le 6$.
9. **Benchmark comparison**: per-domain turn distribution (all within $[1,6]$, 100% solve).
10. **Search-state transitions**: $\mathcal{K}_t \to \mathcal{K}_{t+1}$ under partition, with residual-cluster inset.

## Appendix B. Algorithmic Summary (Pseudocode)

**Algorithm 1. Build optimal decision table.**
```
function BUILD_TABLE(M, root, kmax):
    table <- {}
    walk(root, kmax)
    return table
function walk(S, bud):
    (depth, guess) ← MINIMAX(M, S, bud)
    if guess = none or depth = ∞: return
    table[frozenset(S)] ← guess
    for each bucket B of M[guess, ·] over S with |B| > 1:
        walk(B, bud − 1)
```

**Algorithm 2. Hybrid online decision.** (See §5.2, `DECIDE`.)

**Algorithm 3. Exact minimax.** (See §5.3, `MINIMAX`; memoized on $(\text{frozenset}(S), k)$.)

## Appendix C. Reviewer Criticism Resolution Map

| # | Criticism | Resolved in |
|---|---|---|
| 1 | Insufficient design rationale | §4 Design Rationale (per-subsystem motivation/alternative/tradeoff/evidence) |
| 2 | Weak theoretical treatment | §2, §5.1, §9, §10 (notation, formal defs, math behind execution) |
| 3 | Lacks algorithmic properties | §10 Algorithmic Properties (8 formal propositions) |
| 4 | Related Work reads like survey | §3 Repositioning (similarity/difference/assumption/strength/limit per method) |
| 5 | Numbers unexplained | §15 Results Analysis (every metric interpreted) |
| 6 | Underuses verification | §13 Verification (exhaustive, deterministic, version-stamped, self-play) |
| 7 | Superficial complexity | §12 Complexity (offline vs online, asymptotic/practical, tradeoffs) |
| 8 | No quantitative architecture | §14.2 Architectural Statistics (residual count, coverage, reuse, branching) |
| 9 | Brief discussion | §16 Discussion (strengths/limits/tradeoffs/generalization/future) |
| 10 | No reproducibility | §17 Reproducibility (org, determinism, scripts, regenerable results) |

## Appendix D. Notation Summary

(See §9. The notation table there is the canonical summary and should accompany any standalone reading.)
