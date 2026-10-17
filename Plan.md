# TFWhy — Product Vision & Engineering Roadmap

> **Single source of truth** for product direction, architecture, engineering rules, completed work, and the active roadmap.

| Field | Current position |
| --- | --- |
| Product | `tfwhy` |
| Type | Local-first Terraform engineering assistant |
| Interface | Python CLI |
| Primary users | Platform engineers, DevOps engineers, SREs, Terraform consultants, infrastructure teams |
| Active phase | **No active phase — Phase 11 is complete** |
| Core constraint | No `apply`, no `destroy`, no telemetry, no raw-plan persistence |

**Working agreement:** GitHub Copilot implements bounded tasks. ChatGPT supports architecture, Terraform semantics, test strategy, debugging, and independent reasoning. Automated tests—not an AI assertion—establish expected behavior.

## How to use this document

Attach `Plan.md` to implementation prompts. Before coding, verify the active phase and current repository state. Keep this document updated when a phase, constraint, or meaningful architectural decision changes.

## 1. Product vision
TFWhy should help an engineer understand Terraform's proposed changes, investigate why a resource is changing or being replaced, identify risks and standards violations, propose a conservative correction, and check whether the resulting plan matches the intended outcome.

### Core promise

Understand why Terraform is planning a change, determine what can and cannot be concluded safely, and verify whether a proposed fix achieves the intended result.

### Product principles
1. Evidence before explanation. Findings must be grounded in Terraform plan metadata or inspected configuration. Clearly distinguish confirmed facts, likely explanations, and unknown causes.
2. Deterministic core. Core parsing, rule evaluation, safety classification, and verification must work without AI.
3. Local-first by default. No telemetry or network transmission in core workflows by default.
4. Safe by design. Never run terraform apply or terraform destroy. Never silently mutate user configuration.
5. Privacy by design. Terraform plans can contain sensitive values. Process the input carefully, emit only allowlisted metadata, and never persist raw plans or secrets in history.
6. Honest uncertainty. Missing or ambiguous evidence must result in an explicit unknown/inconclusive outcome, not a fabricated root cause.
7. Useful over clever. Prefer small, testable improvements over agent frameworks, unnecessary dependencies, or broad refactors.
8. Verify outcomes. A successful command or an empty plan is not automatically proof that a proposed refactor is correct. Compare actual behavior with the intended result.
9. Fix bugs whenever found. A reproducible correctness, security, privacy, or destructive-action bug takes priority over feature work, even if discovered during another phase.
10. Follow the roadmap. Do not jump to a future feature because it sounds attractive. Complete the current phase's exit criteria first, except for bug fixes and urgent security corrections.
### Intended long-term CLI experience
These examples describe the direction of the product; check the current CLI help and implementation before claiming each command or option exists.
```bash
tfwhy explain plan.json
tfwhy review --dir ./infra
tfwhy history
tfwhy history show <id>
tfwhy fix --finding TFWHY-001 --dry-run
tfwhy verify --plan plan.json --from <before> --to <after>
tfwhy standards check --dir ./infra
tfwhy why <resource-address>
```
The long-term experience should let an engineer install TFWhy once and run it from any Terraform project directory without entering or cloning the TFWhy source repository. That is a future usability/distribution milestone, not permission to skip the current phase.
## 2. Non-negotiable safety and privacy rules
- Never execute terraform apply or terraform destroy.
- Do not run commands that modify cloud infrastructure.
- Do not silently change, delete, or overwrite user configuration.
- Proposed fixes should be shown as diffs or separate files first. Any write operation must be explicit, narrowly scoped, and approved by the user.
- Do not claim a fix is verified unless the defined checks actually ran and passed.
- Never claim that replace_paths alone proves the upstream root cause. It identifies a replacement-triggering path, not necessarily why that value changed.
- Never treat the mere presence of count, for_each, a timestamp, an AMI lookup, a data source, or a random resource as proof of a root cause.
- Do not print or store raw plan JSON, Terraform state, resource attribute values, environment variables, credentials, or API keys.
- Do not send plans, state, configuration, or metadata to a remote service by default.
- Treat plan JSON as sensitive even when the report is sanitized: parsing it means sensitive input may exist in process memory.
- Use allowlisted metadata extraction. Do not pass complete Terraform change objects into report renderers, logs, history, or future AI prompts.
- Keep history opt-in. Store only necessary sanitized metadata and provide a clear way to inspect and delete it.
- Do not add telemetry by default.
- Do not commit real plan files, state files, credentials, or private employer code.
- If evidence is incomplete or ambiguous, return Unknown, Inconclusive, or an equivalent honest status.
## 3. Architecture direction
Keep the architecture modular and small. Do not build one giant AI prompt that performs all analysis.
```text
CLI / command interface
        |
Input validation and safe file handling
        |
Plan loader + configuration loader
        |
Metadata extraction / sanitization boundary
        |
Normalized internal models
        |
+----------------+------------------+----------------+
| Plan summary   | Replacement       | Standards and  |
| and actions    | analysis          | security rules |
+----------------+------------------+----------------+
        |
Evidence-backed findings + severity + confidence
        |
Fix proposal engine / verification engine
        |
Report renderers: terminal / Markdown / JSON
        |
Opt-in sanitized local history
        |
Future optional AI explanation adapter (not authoritative)
```
### Architecture rules
- Keep parsing, analysis, verification, presentation, persistence, and external command integration separate enough to test independently.
- Use shared finding/result models where practical: stable finding ID, severity, resource/file reference, evidence, explanation, recommendation, and confidence/status.
- Keep raw Terraform values outside normalized findings and renderers.
- Treat HCL text scanning as potentially ambiguous. Prefer a maintained HCL parser if a demonstrated correctness need justifies the dependency; do not add one without evaluating scope, maintenance, license, and tests.
- External Terraform commands must be invoked safely, with clear distinction between unavailable tools, validation failures, and successful checks.
- Do not make AWS credentials or a cloud account prerequisite for analyzing supplied plan JSON or static Terraform configuration.
- Keep provider/cloud-specific logic optional and separate from the core.
- Avoid broad refactors during a focused phase. Add abstractions when they solve a demonstrated problem.
### Likely internal areas
Names may differ in the actual repository; do not rename modules simply to match this list.
- CLI and argument handling
- Plan JSON parsing and metadata extraction
- Configuration/HCL inspection
- Plan summary and action classification
- Replacement analysis and confidence/evidence rules
- Standards/security rules
- Fix proposal and verification
- Sanitized history
- Report renderers
- Packaging and tests
- Future optional AI adapter
## 4. Current repository status

_Verified against the repository and latest local smoke tests on 2026-10-17. Counts below are evidence from the current workspace, not a permanent guarantee._

| Milestone | Status | Evidence |
| --- | --- | --- |
| Plan explainer | Complete | Plan actions, replacement metadata, malformed input handling, terminal/Markdown/JSON reports |
| Replacement analysis | Complete | Conservative paths, action reasons, configuration evidence, confidence states |
| Standards/security review | Complete | Configurable standards, selected AWS checks, optional Terraform integrations |
| Fix proposals/verification | Complete | Safe diffs, explicit approval, verified/not-verified/inconclusive outcomes |
| Local history | Complete | Opt-in sanitized JSON history, recurrence observation, corruption handling |
| Packaging/release readiness | Complete | Editable install, console entry point, `.gitignore`, GitHub Actions, CLI smoke tests |

**Latest evidence:** the full Python suite passes **58 tests**. Phase 11 exercised terminal, Markdown, and JSON drift output; positive, absent, malformed, and privacy-protected drift metadata; and bounded legacy-provider migration guidance. It uses only user-supplied plan JSON and static configuration. Terraform `v1.16.6` is installed; direct validation of the AWS static fixture cannot proceed because `registry.terraform.io/hashicorp/aws` is unavailable locally, so no configuration-validation result is claimed.


> **Evidence note:** Historical milestone labels describe completed scope. Always rerun the current suite and smoke tests before making a new completion claim.
### Known scope boundaries
- TFWhy is currently a Python CLI, not yet a polished standalone binary or globally installed end-user experience.
- Corporate-style testing has been performed using synthetic Terraform configuration and plan JSON without creating AWS resources. Its reported tests passed; use the actual latest test report for details.
- The user does not require AWS integration to test the current core.
- Replacement root-cause analysis is intentionally conservative and must not overstate what plan metadata proves.
- Fix generation supports only the cases implemented and tested; do not imply it can safely refactor arbitrary Terraform.
- Terraform's own validation/formatting checks depend on the Terraform executable being installed. Distinguish mocked integration tests from real Terraform execution.
- Current implementation claims must be checked against the code before documentation, marketing, or release claims are made.
## 5. Roadmap and phase gates
Only the current phase is active. A future phase may be refined after the previous phase exits, but do not implement it early. Bug fixes and urgent security fixes are always allowed and take priority.
### Phase 7 — Real-world reliability hardening **(COMPLETE)**

**Goal:** Make the existing MVP reliable against realistic Terraform projects without expanding product scope.

**Tasks**
- [x] Inspect the current code, README, tests, and the completed corporate-style project test results.
- [x] Reproduce and fix any real defects in plan JSON parsing, unsupported/malformed input, and report rendering.
- [x] Check replacement evidence and confidence classifications; ambiguous causes must remain unknown.
- [x] Check nested module addresses, count, for_each, locals, variables, data sources, and configuration matching for false positives or cross-module matches.
- [x] Check standards/security review rules for material false positives and false negatives.
- [x] Check fix proposals for unsafe assumptions, unintended overwrites, and incorrect resource-address mappings.
- [x] Check verification logic against the intended result, including unexpected create/replace/delete operations.
- [x] Check history privacy, schema validation, corruption behavior, and safe file operations.
- [x] Add a focused regression test for every reproducible bug fixed.
- [x] Run the full test suite and relevant CLI smoke tests, including terminal/Markdown/JSON output where relevant.
- [x] Update docs only when behavior or limitations genuinely change.
**Constraints:** No new product features, AI, cloud integrations, dependencies, global installation work, or broad refactors. Do not invent bugs to justify the phase. If no meaningful issue is found, leave the code unchanged and record the evidence.

**Exit criteria:** Complete. The public-ingress variable-default false negative was fixed with public/private regression coverage; the full suite passes 35 tests; terminal, Markdown, and JSON review output was checked. Computed or indirect variable values remain ambiguous, and module-addressed replacement analysis can remain `Unknown`.

### Phase 8 — Install once, run from any Terraform project **(COMPLETE)**

**Goal:** Remove the need for engineers to enter or clone the TFWhy repository for everyday use.

**Current work:**
- [x] Document editable installation and an individual-developer `pipx` workflow.
- [x] Ensure the `tfwhy` executable is available after installation; verify through the repository virtual environment.
- [x] Allow `review` to inspect the caller's current directory when `--dir` is omitted.
- [x] Preserve explicit plan and project-directory options; `explain` still requires an explicit plan path.
- [x] Keep history in `~/.tfwhy/history.json` by default, with opt-in saving and `--history-file` override.
- [x] Document upgrade, troubleshooting, supported Python version, and offline usage.
- [x] Verify installation through `pipx` from the local repository; no published package exists to test.
- [ ] Define safe plan discovery only if a demonstrated workflow requires it; do not silently choose an arbitrary plan.
- [ ] Consider standalone binaries only if user feedback demonstrates a real need.
**Exit criteria:** Complete for local repository installation. A clean isolated `pipx install .` environment ran `tfwhy --help` and analyzed a synthetic plan from outside the source repository. PyPI installation remains unverified because no package is published.

### Phase 9 — Improve Terraform configuration understanding **(COMPLETE)**

**Goal:** Reduce false positives and improve evidence linking between plan metadata and configuration.
- [x] Evaluate HCL parsing versus current scanning based on measured limitations; retain the dependency-free scanner because module-address and brace-boundary fixes are covered without a parser dependency, and document its limits.
- [x] Match complete module-qualified addresses through literal local child-module sources, and report safe relative file-and-line locations.
- [x] Trace direct single-line variable, local, data-source, and managed-resource references where an unambiguous declaration is available.
- [x] Keep conditionals, indirect expressions, and unsupported constructs Unknown; count, for_each, indexed addresses, and moved blocks do not establish a replacement cause.
- [x] Add focused regressions for module isolation, interpolation-brace cross-matching, collected Phase 7 regressions, direct references, source locations, count, for_each, moved blocks, and a format `1.1` fixture.
- [x] Document the plan-format/version compatibility boundary and configuration-scanner support matrix.
**Exit criteria:** Complete. The 2026-10-17 suite passes 43 tests and demonstrates corrected module matching, prevented interpolation-brace cross-matching, and conservative addressing classifications without a new dependency or a Terraform language evaluator.

### Phase 10 — Import and permission assistance **(COMPLETE)**

**Goal:** Help engineers bring existing resources under Terraform and spot potentially risky permissions.
- [x] Add a preview-first `tfwhy import` command using only an explicitly supplied managed-resource address and import identifier.
- [x] Generate a starter resource body only for a root, unindexed `aws_s3_bucket`, where the supplied import ID is the bucket name; otherwise explain why a body was not generated.
- [x] Add static `jsonencode` IAM Allow findings for global/service action wildcards and global resource wildcards, without reporting policy contents.
- [x] Add narrow findings for all-protocol unrestricted security-group egress and public network-ACL SSH/RDP or all-protocol ingress; retain existing security-group ingress coverage.
- [x] Use stable review finding IDs, severity, evidence, rationale, and remediation; explicitly state that a finding does not establish exploitability.
- [x] Render unified diffs by default and write only after `--apply --approve --out`; refuse an existing output path and never create parent directories implicitly.
- [x] Add synthetic import/permission fixtures, positive/negative/malformed/ambiguity/privacy tests, and document unsupported cases.
**Exit criteria:** Complete. The 2026-10-17 suite passes 52 tests; the generated import fixture passes `terraform fmt -check`; static permission findings are evidence-backed and conservative.

### Phase 11 — Drift and upgrade assistance **(COMPLETE)**

**Goal:** Explain supported drift and version migration cases using plans the user generates.
- [x] Accept user-generated refresh-only plans when their JSON contains Terraform's supported `resource_drift` metadata; TFWhy does not claim the JSON identifies plan mode.
- [x] Separate `resource_changes` (planned resource changes) from `resource_drift` (Terraform-detected remote differences), including only structural `relevant_attributes` evidence.
- [x] Explain that detected remote differences do not establish who or what caused them, or prove they caused a planned action.
- [x] Add `TFWHY-UPGRADE-001` for the literal legacy `hashicorp/terraform` provider source, based on HashiCorp's documented incompatibility with Terraform 0.11 and later.
- [x] Record OpenTofu behavior as unsupported because no concrete reproducible JSON-compatibility case was available.
- [x] Test supported format `1.0`/`1.1` drift inputs, no-drift, malformed, privacy, and terminal/Markdown/JSON output cases.
Constraints: No default direct AWS access and no automatic infrastructure changes.
**Exit criteria:** Complete. The 2026-10-17 suite passes 58 tests. Synthetic format-1.x fixtures cover detected remote drift, ordinary non-drift plans, malformed structural metadata, and safe output. No new dependency, cloud access, provider call, AI service, or OpenTofu compatibility claim was added.

### Phase 12 — Optional AI explanations **(FUTURE; ONLY AFTER CORE RELIABILITY)**

**Goal:** Make evidence easier to understand without delegating correctness or safety decisions to an LLM.
AI is not required for the core product and must not be introduced just to make TFWhy appear more advanced.
Intended role of AI
- Explain deterministic findings in plain language.
- Summarize multiple findings and their relationships when the evidence supports the connection.
- Help users understand trade-offs between proposed remediations.
- Answer questions about a finding using only approved evidence supplied for that request.
AI must not
- Replace plan parsing, rule evaluation, confidence classification, or verification.
- Invent root causes or convert unknown evidence into certainty.
- Execute Terraform, access cloud accounts, apply changes, or autonomously edit files.
- Receive raw plans, state files, full source trees, credentials, or attribute values by default.
- Be required for core CLI commands or offline operation.
Required design and safety gates
- [ ] Define an explicit provider adapter so the core does not depend on one model vendor.
- [ ] Keep AI disabled by default and require explicit opt-in before any network request.
- [ ] Show what sanitized evidence will be sent and to which provider before first use; provide a way to disable AI completely.
- [ ] Build prompts only from allowlisted, sanitized finding metadata. Never pass the raw plan or full configuration as a convenience.
- [ ] Redact or omit resource addresses and metadata when they could reveal sensitive information, with controls documented for users.
- [ ] Treat model output as untrusted text; do not execute returned code or commands.
- [ ] Require the model to distinguish supplied evidence from interpretation and preserve Unknown/Inconclusive states.
- [ ] Keep deterministic findings unchanged if the AI provider is unavailable, wrong, or rate-limited.
- [ ] Add tests with synthetic secret markers, prompt-injection-like content in configuration/comments, malformed model responses, provider failures, and claims unsupported by evidence.
- [ ] Document data handling, provider retention considerations, costs, and offline alternatives.
- [ ] Evaluate whether local models are worthwhile only after there is a clear user need and realistic maintenance plan.
**Exit criteria:** AI is optional, auditable, privacy-aware, tested against unsupported claims, and never authoritative for safety or verification.

### Phase 13 — CI and pull-request workflows **(FUTURE)**

**Goal:** Bring useful findings into an engineer's normal review workflow.
- [ ] Add a stable machine-readable output contract and exit-code policy.
- [ ] Support CI usage without interactive prompts.
- [ ] Define configurable severity thresholds and failure behavior.
- [ ] Consider pull-request comments only after local CLI output and finding IDs are stable.
- [ ] Ensure CI logs do not leak secrets or raw plans.
- [ ] Test provider failures, permissions, duplicate comments, and noisy findings.
**Exit criteria:** CI behavior is predictable, configurable, documented, and does not make infrastructure changes.

### Phase 14 — Team and business validation **(FUTURE)**

**Goal:** Validate demand before building hosted infrastructure or paid features.
Potential capabilities:
- Shared standards and policy packs.
- Team-level history and reports.
- Pull-request collaboration.
- Optional hosted AI explanations.
- Centralized administration, if validated by customers.
Before implementing a hosted service:
- [ ] Interview target users and observe real workflows.
- [ ] Measure repeat usage, false-positive tolerance, trust, and time saved.
- [ ] Identify a specific problem teams are willing to pay to solve.
- [ ] Define tenant isolation, data retention, access control, auditability, and deletion requirements.
- [ ] Reassess the local-first promise and make hosted features clearly optional.
**Exit criteria:** Real users repeatedly use TFWhy and there is evidence of demand for a specific team feature. Downloads or social engagement alone are not product-market fit.

## 6. Testing and release policy

Every phase and bug fix must follow this policy.

### Required test layers
1. Unit tests: Parsers, analyzers, models, formatters, and helpers.
2. Golden/fixture tests: Known plans produce expected output.
3. Regression tests: Every reproducible bug fixed gets a test where practical.
4. Negative tests: Malformed input, missing fields, unsupported actions/versions, ambiguous configuration, and failed external tools.
5. Privacy tests: Synthetic secret markers must not appear in reports, logs, history, diffs, or AI payloads.
6. Integration tests: Synthetic Terraform projects and Terraform-generated plans when Terraform is available.
7. CLI smoke tests: Commands, output formats, error paths, and exit codes affected by the change.
8. Packaging tests: Installation and invocation outside the source repository when packaging changes.
9. Cross-platform/compatibility tests: Expand when supported platforms and versions are declared.
### Standard completion checklist
- [ ] Inspect existing code and behavior before changing it.
- [ ] Reproduce the bug or define measurable acceptance criteria.
- [ ] Make the smallest effective change.
- [ ] Add focused tests, including a regression test for each fixed bug where practical.
- [ ] Run the relevant tests and the full suite.
- [ ] Run relevant CLI smoke tests.
- [ ] Review the diff for unrelated changes, secret leakage, unsafe file operations, and misleading claims.
- [ ] Update documentation only when needed.
- [ ] Report actual commands and results; never claim tests ran if they did not.
- [ ] Report remaining limitations and anything that could not be tested.
If a test cannot run because Terraform or another tool is unavailable, say so clearly. Mocked tests do not prove that the real executable works in that environment.
### Bug-fix policy
Bugs are not restricted to a specific roadmap phase. When any prompt, test, or user report reveals a bug:
1. Determine whether it is reproducible and assess severity.
2. Fix critical security/privacy/destructive-action bugs immediately and stop unrelated work if necessary.
3. Fix reproducible correctness bugs with a minimal patch and regression test.
4. Run the relevant tests and full suite.
5. If a safe fix is not possible in the current scope, document impact, workaround, and reason for deferral in the phase notes.
6. Update this plan's current status or decision log when the bug changes scope, constraints, or roadmap decisions.
Do not leave a known serious bug in place merely because the roadmap says a different phase is active.
## 7. Working with Copilot and ChatGPT
Attach this plan.md to repository implementation prompts. Use the following instruction at the top of each prompt:
Treat plan.md as the source of truth. Inspect the current repository and identify the active phase before coding. Work only on the requested task within that phase. Do not jump to future phases or add unrelated features. Fix reproducible bugs discovered along the way, add regression tests, run relevant tests and the full suite, and report actual results. Never claim unsupported behavior or test results. If this request conflicts with the plan, explain the conflict before making changes. Update plan.md only when the phase status, roadmap, constraints, or an architectural decision genuinely changes.

### Copilot responsibilities
- Inspect the current repository and relevant tests first.
- Implement one bounded task at a time.
- Make the smallest change that meets acceptance criteria.
- Include tests and validation in the same task prompt to reduce repeated work.
- Report files changed, bugs fixed, tests run/passed/failed, smoke-test results, and limitations.
- Do not mark a phase complete based solely on code generation; use its exit criteria.
### ChatGPT responsibilities
- Help interpret behavior, Terraform semantics, architecture trade-offs, failures, and test evidence.
- Challenge unsupported root-cause claims and unsafe assumptions.
- Help prepare concise, implementation-ready prompts.
- Respect the current phase and avoid adding work without a clear reason.
- Do not request real credentials, production state, sensitive plan JSON, or private employer code.
### User approval
The user owns the final decision to accept changes, commit them, release the product, or enable any behavior that writes files or sends data externally.
## 8. Product validation and success measures
Do not wait until every future phase exists before showing the product, but do not make broad reliability claims without evidence.
### Early validation
- [ ] Compare summaries against Terraform's own plan output.
- [ ] Use synthetic plans and realistic multi-module test projects.
- [ ] Record false positives, false negatives, and unsupported cases.
- [ ] Compare with existing tools where useful; focus on a better workflow, not duplicating every scanner.
- [ ] Demonstrate the tool with synthetic infrastructure and sanitized output.
- [ ] Ask engineers whether the output changes a real decision or saves investigation time.
### Possible initial success measures
These are targets, not current achievements:
- External engineers can install and use TFWhy from their own project directory.
- At least 10 people outside the creator's immediate team try it.
- At least 3 users return to use it without prompting.
- Findings have a tolerable false-positive rate on representative projects.
- Users can explain why they trust or reject a finding.
- Reported security or destructive-action bugs are investigated and regression-tested where possible.
Measure trust, repeat use, and useful time saved—not only downloads or social-media engagement.
## 9. Deferred decisions and explicit non-goals
Do not prioritize these until the roadmap and user evidence justify them:
- A final logo or extensive branding work.
- A hosted dashboard before validated demand.
- Direct cloud account access as a core requirement.
- Automatic Terraform apply/destroy or autonomous infrastructure changes (prohibited).
- A complex multi-agent framework.
- AI as a requirement for core features.
- A proprietary replacement for mature linters without a demonstrated gap.
- Enterprise authentication, billing, or centralized storage before customer validation.
- Standalone binaries before the install-once CLI experience is proven and user needs justify them.
## 10. Decision log and progress tracking
Update this section only when a meaningful decision, phase transition, or constraint changes. Do not rewrite historical facts to make progress look better.
| Date | Decision/status | Reason or evidence |
| --- | --- | --- |
| 2026-10-16 | Reported milestones 1–6 complete; Phase 7 is current. | Existing CLI capabilities, packaging work, and corporate-style synthetic testing were reported complete. Verify against the current repository and test output. |
| 2026-10-16 | Phase 7 reliability hardening completed; Phase 8 is current. | Fixed the public-ingress false negative for direct literal variable defaults, added public/private regression tests, and verified 35 passing tests plus terminal/Markdown/JSON review output. Computed or indirect values and module-addressed replacement matching remain intentionally conservative. |
| 2026-10-16 | Phase 8 completed for local repository distribution. | Isolated `pipx install .` and outside-project CLI smoke passed; `review` defaults to the caller's directory; history stayed in the user data path. No PyPI package exists, so published-package installation remains unverified. |
| 2026-10-17 | Phase 9 activated. | The current implementation and regression tests will be audited for configuration-to-plan matching errors before making bounded improvements. |
| 2026-10-17 | Phase 9 completed. | Fixed module-address matching and interpolation-brace cross-matching; added bounded direct-reference/source-location evidence; corrected indexed-address confidence to Unknown; the full suite passed 43 tests. A maintained HCL parser was not justified by the demonstrated cases. |
| 2026-10-17 | Phase 10 activated. | Begin with a bounded, local-only import proposal and static IAM/network permission review; do not infer cloud resource settings or exploitability. |
| 2026-10-17 | Phase 10 completed. | Added preview-first explicit import proposals with guarded writes, one truthful S3 starter configuration, IAM wildcard and narrow network findings, scanner-boundary and blank-tag bug fixes, and 52 passing tests. No provider, cloud, AI, network service, or dependency was added. |
| 2026-10-17 | Phase 11 activated. | Audit plan JSON's `resource_drift` metadata and add only evidence-backed drift and upgrade guidance without cloud access or raw-value reporting. |
| 2026-10-17 | Phase 11 completed. | Added local `drift` reporting for explicit `resource_drift`, separate safe planned/drift evidence, and one source-backed legacy provider migration check. The full suite passes 58 tests; refresh-only mode and OpenTofu compatibility remain unclaimed without JSON evidence or a reproduced case. |
| 2026-10-16 | Global/standalone installation is deferred to Phase 8. | The project will follow the agreed phase order instead of jumping ahead. |
| 2026-10-16 | AI is a future optional layer, not part of the deterministic core. | Privacy, reliability, and evidence quality must come first; AI must not decide safety or verification. |


## Current next action

Phase 11 is complete. Do not begin Phase 12 without a new request. Retain the drift boundary: only explicit `resource_drift` metadata is reported as detected remote drift; it does not prove refresh-only mode, a cause, or who made a change. Retain the Phase 10 boundaries: user-supplied addresses and identifiers only, one supported S3 starter body, literal IAM `jsonencode` policies, and Unknown/no-finding behavior for computed or unsupported constructs.

> **Guiding principle:** Build a trustworthy Terraform engineering tool first, make it easy to install second, add carefully bounded intelligence later, and validate business demand before investing in hosted/team features.
