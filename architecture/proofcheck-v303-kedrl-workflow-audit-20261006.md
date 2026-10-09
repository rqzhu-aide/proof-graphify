**Proof-check v3.0.3: KEDRL database and workflow audit, 2026-10-06**

The main remaining friction is translating source examination into accepted, correctly connected database records. The three-stage design and coordinator-owned database remain workable. The normal authoring path does not yet cover all ordinary source structures, and coordinators still write substantial custom mapping and recovery code. That code sometimes repeats work, restores old data, or misreports the saved state.

Three GPT-6.1 Sol subagents at xhigh examined Claude, Codex/DSH, and GLM/K3 separately. The coordinator compared their findings, independently aggregated all six harvested databases, checked key statement histories and finding targets against the original stores, and inspected the relevant authoring and support-credit implementation. This audit concerns construction, assignments, corrections, integration and completion. It does not adjudicate the paper's mathematics.

The two requested roots are:

- [Main test](C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v3.0.3+kedrl-full__20261005-194535)
- [Claude rerun](C:/Users/zrq/projects/skills/_testing-center/results/stat-proof-check@v3.0.3+kedrl-full__20261006-005001)

Original databases were opened read-only with immutable SQLite connections. Their hashes were unchanged after the aggregate inspection. No skill or original result was modified.

**What actually finished**

| Run | Harness duration | Current items / arguments | Unsuccessful saved submissions | Observed outcome |
|---|---:|---:|---:|---|
| Claude, first test | 21m03s | 0 / 0 | 0 | Evidence captured, but no graph or frozen audit before host termination |
| Codex | 89m18s | 60 / 41 | 2 of 147 | Frozen release and HTML; actual model task ended after about 46 minutes |
| DSH | 27m02s | 22 / 21 | 77 of 144 | Frozen release and HTML, with representation and reporting defects |
| GLM | 89m34s | 25 / 14 | 18 of 78 | Frozen release and HTML, but two reverted statement corrections remain |
| K3 | 177m17s | 25 / 20 | 3 of 72 | Frozen release and HTML; substantial serial review time |
| Claude, supplied rerun | 75m02s | 36 / 23 | 3 of 96 | Frozen release and HTML; repeated intake and a review-credit mismatch |

Arguments are stored graph records, not a count of all review questions. A larger graph is not automatically unnecessary, and a smaller graph is not automatically efficient. Different choices about grouping, external results and unnumbered claims affect these counts. Unsuccessful submissions are attempts, not distinct defects or repeated scientific examinations. Idempotent replays are also not all represented as separate saved submissions.

All five completed runs report all their registered obligations finished. That establishes completion of their registered inventory, not consistent coverage of the whole paper or correctness of their repairs.

**1. Normal graph authoring does not match the promised examination unit**

The skill says an examination can cover a written proof or meaningful subsection. However, `authoring.py` accepts only theorem, lemma, proposition and corollary through `add-unit`. Both PI runs attempted derivations and encountered that restriction.

K3 relabeled six meaningful sections as lemmas to obtain the ordinary workflow. GLM used lower-level owner-attached derivation/claim records. Four of GLM's sections were explicitly included in a primary examination, but equivalent independent coverage is not demonstrated by the saved independent delivery and records. Packet absence alone cannot establish that a worker never read the original PDF.

DSH also registered Assumptions 2.1, 2.3 and 3.1 as lemmas, despite noting that they need no proof. They then received primary examinations, independent examinations and reconciliation. Assumption 3.1's unavailable proof status affected Theorem 3.2. This contradicts the existing instruction that named assumptions remain setup context.

Attribution: the derivation restriction is a confirmed tooling mismatch. Assumption misclassification is an agent authoring error, encouraged by the convenience of the proof-unit helper; an appropriate lower-level route already exists. The practical problem is that the easiest route changes the meaning of the graph and its required work.

The narrow improvement direction is to make ordinary claims, meaningful derivations and setup records easy to represent accurately. It is not to turn every intermediate equation into a separately reviewed theorem.

**2. Coordinators still reconstruct administrative records and recovery loops**

DSH's 77 unsuccessful submissions included 61 primary schema failures. Its own normalization scripts successively added forbidden envelope fields, removed required row fields, and moved coverage into the wrong place. Retrying whole batches multiplied each misunderstanding. This is not evidence that valid generated scaffolds were rejected. Most of those schema failures occurred in about three minutes, so the count should not be presented as the cause of an hours-long run.

The Claude rerun submitted the same Matérn packet 49 times in its custom intake loop: one initial submission and 48 idempotent replays. The loop did not handle the accepted-but-partial result and its remaining tasks. Claude later recognized the replay, removed duplicate work folders, completed the affected question, and added a seen-packet stop. The database avoided duplicate scientific records, but that did not stop the coordinator's work loop.

K3 encountered a different confusion: a reviewer used partial examination to describe a missing written proof step, although the omission itself had been assessed. The coordinator recognized the distinction, but commissioned another whole review rather than obtaining a short clarification of the returned extent. That added about eight minutes and was followed by duplicate findings for the same issue.

Attribution: these are agent mapping and orchestration failures around an interface that remains costly to use. The instructions already say to use generated scaffolds, avoid unchanged retries, and distinguish assessed proof omissions from unexamined material. Adding more copies of those rules would not address the recurring burden.

The useful direction is easier reuse of the generated response, a clear distinction between saved work and remaining work, and local correction of administrative interpretation without another proof examination.

**3. Corrections can be undone or misreported during recovery**

GLM's item history provides a direct example. Two statements first used a minus sign, were corrected to plus in version 2, then returned to minus in version 3. During conflict recovery, the coordinator built paired correction inputs from old template bodies. The helper saved those supplied bodies faithfully. The final records still contain the minus expressions, while their notes and final report claim the plus-sign corrections were retained.

The renewed reviewer received those actual version-3 records and objected. This was not a stale argument-question generation defect. Recovery had restored old data. Four additional independent reviews and integration followed; the whole correction-to-integration arc lasted about 24 minutes, not all of which can be classified as avoidable overhead.

DSH's final report says a coordinator finding was saved against Theorem 3.2, but its actual target is the argument for S2.2. The trace shows reassignment after a task-scope rejection so it could fit an available integration packet. Four findings about corrected database transcription errors also remain open after failed resolution attempts, despite stronger cleanup claims in the prose.

Attribution: these are observed authoring, mapping and reporting errors. A successful release receipt does not establish that a claimed repair survived. The useful direction is a correction route based on current records and a returned description of what was actually changed, rather than repeated reconstruction of full old bodies. Reporting should follow the saved outcome, including an unresolved repair if one remains.

**4. Some connection statuses do not reflect the actual use or saved examination**

Codex linked a construction to the aggregate S2.2 theorem using a definition edge, while explicitly saying only its regular-law class definition was needed. The aggregate theorem's adverse support still affected the consumer. Codex split out the definition and refreshed the affected records, reusing saved opinions with an explicit note that no new scientific review occurred. This cost about four minutes. The source node was too broad for that use, and coarse support propagation amplified the representation choice.

In the Claude rerun, both primary and independent examinations explicitly discuss S2.12's reuse of Theorem 3.3's proof steps. The delivered packet includes the borrowed proof pages. However, the saved coherent source scope contains only S2.12's own statement/proof anchors. `coherent.py` requires a use's evidence to fall within that narrower set before inheriting whole-unit review credit. The use therefore appears unassessed and its argument partial, although there are no missing registered obligations and independent review is complete.

This does not establish that either theorem should receive an unconditional mathematical verdict. It identifies a mismatch in credit for the local connection that was explicitly examined. The needed correction is accurate representation and recognition of the actual reviewed use, not an additional proof sweep.

**5. Scheduling and host behavior must be separated from graph defects**

The first Claude coordinator ended its turn while five workers were still running. The host's background-task wait ceiling then terminated them. It had captured 95 anchors but no graph items. An exit code of zero did not mean completion. The supplied rerun used four primary groups and five independent groups and finished.

K3 made 11 independent-review CLI calls serially. Their elapsed intervals total 94.2 minutes, about 53% of the run. Smaller packets alone would not remove that scheduling cost.

Codex's raw session ends after about 46 minutes. Its harness remains active for another 42m56s without recorded model work. The cause of that tail is unproven, so it must not be attributed to continued database repair. DSH had brief Windows temporary-directory write/cleanup failures during freezing and rendering, followed by successful recovery; these did not restart scientific work.

**What the revision did improve**

All current private scopes in these stores are empty. The old proliferation of ordinary theorem hypotheses into private assumptions is not evident here. DSH's separate assumption-as-lemma error should not be confused with that earlier problem.

Codex used local primary drafts and custom coordinator consolidation, including merging a contextual copy of Lemma S2.1 into its canonical item. Claude's inspected shared suppliers also map to single canonical nodes. These spot-checks support the local-draft approach; neither run directly establishes the behavior of the `consolidate-drafts` helper, because both used custom mapping. This was not an exhaustive semantic deduplication audit.

There is no evidence that simultaneous subagent database writes caused the observed conflicts. In DSH, children read evidence and wrote responses; the coordinator changed source statements or retired a connection after packets had been prepared. Those changes explain the stale-input conflicts. Codex's local drafts avoided much of that early packet invalidation.

**Priority judgment**

The highest-value work is to simplify the bridge from local drafts and returned judgments into correct shared records: support the intended ordinary record types, preserve current data during correction, make accepted versus unfinished work easy to distinguish, and retain findings on their true targets. The two connection/status mismatches deserve narrow fixes as well.

These results do not justify extra audit stages, universal re-review after corrections, more compulsory proof units, or a wholesale database redesign. The database's many generated records are not by themselves the demonstrated problem. The demonstrated problem is how much of their coordination and repair still falls to agent-written scripts.

**Supporting evidence**

- [Claude audit](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-results-audit-20261006/claude/findings.md)
- [Codex and DSH audit](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-results-audit-20261006/codex-dsh/REPORT.md)
- [GLM and K3 audit](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-results-audit-20261006/pi/pi-workflow-audit.md)
- [Cross-run database inventory and receipts](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-results-audit-20261006/overview.json)
- [Claude replay evidence](C:/Users/zrq/projects/skills/stat-paper-skills/stat-paper-skills/tmp/v303-results-audit-20261006/claude/replay-evidence.json)
