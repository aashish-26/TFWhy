# Terraform Agent — Product & Engineering Execution Plan

**Working name:** `tfwhy`  
**Product type:** Local-first Terraform engineering assistant  
**Development approach:** GitHub Copilot for implementation; ChatGPT for review, testing strategy, debugging, and design decisions  
**Initial language:** Python  
**Initial interface:** CLI  
**Initial users:** Platform engineers, DevOps engineers, Terraform consultants, and small infrastructure teams

---

## 1. The final product we are building

The user runs one command against a Terraform plan and, optionally, the Terraform project directory.

The tool explains the planned changes, identifies risky operations, investigates replacement causes, checks engineering standards, and proposes fixes with supporting evidence.

Over time, it remembers previous runs locally, identifies recurring infrastructure problems, helps import existing resources, assists with upgrades, and integrates into CI pipelines.

### The product's core promise

**Understand why Terraform is making a change, determine whether it is safe, and verify whether the proposed fix resolves the problem.**

### What the finished CLI should look like

```bash
tfwhy explain plan.json
tfwhy review --plan plan.json --dir ./infra
tfwhy history
tfwhy why aws_instance.app
tfwhy fix --finding TFWHY-001 --dry-run
tfwhy standards check --dir ./infra
```

These commands represent the intended product interface, not commands that all exist yet.

### What the tool must never do

- Never run `terraform apply` or `terraform destroy`.
- Never make unapproved changes to the user's files.
- Never send raw plan JSON, state files, or source code to an AI provider by default.
- Never store attribute values in plan history.
- Never claim that a fix is verified unless the relevant checks actually passed.
- Never present an AI guess as a proven root cause.
- Never collect telemetry by default.

---

## 2. Product architecture

Build one product with several deterministic analyzers underneath it. Do not build one giant AI prompt that attempts to perform every check.

```text
                    USER
                      |
                 tfwhy CLI
                      |
               Input validation
                      |
             Plan and code loader
                      |
          Metadata extraction boundary
                      |
          +-----------+-----------+
          |           |           |
      Plan summary  Replacement  Standards
                    analysis      checks
          |           |           |
          +-----------+-----------+
                      |
               Normalized findings
                      |
              Evidence and severity
                      |
             Optional AI explanation
                      |
                Report generator
                      |
           Terminal / Markdown / JSON
                      |
          Proposed fixes and verification
                      |
             Local history, later
```

### Architecture rules

1. Analyzers must work without AI.
2. Each analyzer must be independently testable.
3. All findings must use a shared schema.
4. Findings must include evidence and explain uncertainty.
5. The report generator must never receive raw Terraform attribute values.
6. Fixes must produce diffs or new files, not silently overwrite the user's configuration.
7. Verification must report its actual result, including failure.
8. History must store only explicitly approved metadata.

---

## 3. Technology stack

| Component | Initial decision |
|---|---|
| Language | Python 3.11+ |
| CLI | Typer or argparse; keep the existing argparse scaffold initially |
| Testing | pytest, plus security-focused tests |
| Plan parsing | Python JSON parser with an explicit metadata extraction layer |
| Terraform configuration | python-hcl2 or another maintained HCL parser, evaluated before integration |
| Formatting | Terraform's own `terraform fmt` |
| Validation | `terraform validate` |
| Standards and security | Existing tools such as TFLint and Trivy, where appropriate |
| AI | Optional provider adapter; no dependency for core functionality |
| Reports | Terminal, Markdown and JSON |
| History | Local SQLite database or versioned JSON records; decide before implementation |
| CI | GitHub Actions for tests and packaging |
| Distribution | Python package initially; standalone binaries can come later |

Do not add a dependency just because it is popular. Each dependency must have a clear purpose, a maintained release history, a license compatible with the project, and tests covering our integration.

---

## 4. Development roadmap

### Phase 0 — Establish the foundation

**Goal:** Make the repository reproducible and safe to develop.

Tasks:

- [ ] Create a Git repository.
- [ ] Add a README, license, `.gitignore`, and contribution notes.
- [ ] Create a virtual environment and document installation.
- [ ] Set up automated tests in GitHub Actions.
- [ ] Add a synthetic Terraform plan fixture.
- [ ] Ensure plan files, state files, `.env` files, and API keys are excluded from Git.
- [ ] Add a documented Python version policy.
- [ ] Record the supported Terraform plan JSON format versions.
- [ ] Establish a rule that every feature requires tests and acceptance criteria.

**Exit criteria:** A fresh checkout can install the package and pass all tests using documented commands.

### Phase 1 — Build the plan explainer

**Goal:** Make Terraform plans easier to understand without using AI.

Tasks:

- [ ] Parse the plan JSON format and validate its structure.
- [ ] Summarize resources being created, updated, deleted, replaced, read, or left unchanged.
- [ ] Group results by action and risk.
- [ ] Identify replacements separately from ordinary updates.
- [ ] Show resource addresses and types.
- [ ] Display replacement attribute paths when available.
- [ ] Identify malformed or unsupported input.
- [ ] Generate terminal, Markdown, and JSON reports.
- [ ] Handle empty plans and resource-less plans.
- [ ] Test unknown actions, missing fields, malformed paths, and unsupported format versions.

**Exit criteria:** The report matches the actions in the input plan and never includes the fixture's attribute values.

### Phase 2 — Build the replacement-cause finder

**Goal:** Explain why a resource is being replaced.

Tasks:

- [ ] Read Terraform's replacement paths when present.
- [ ] Read supported action-reason metadata.
- [ ] Associate a replacement path with the relevant resource.
- [ ] Locate related configuration expressions when a project directory is supplied.
- [ ] Trace references to variables and expressions where feasible.
- [ ] Recognize common patterns such as changing AMI lookups, timestamps, random values, and resource addressing changes.
- [ ] Distinguish confirmed evidence from possible explanations.
- [ ] Return an explicit confidence level or evidence status.
- [ ] Report when Terraform does not provide enough information to determine the cause.

**Example result:**

> Resource `aws_instance.app` is scheduled for replacement. Terraform identifies `user_data` as a replacement-triggering attribute. The configuration appears to derive this input from a changing expression. Inspect the expression and its inputs before changing the resource.

Do not claim that a timestamp or AMI lookup is the cause unless the available evidence supports that conclusion.

**Exit criteria:** Every replacement finding includes its evidence, and unsupported root-cause claims are rejected by tests.

### Phase 3 — Add configurable code standards

**Goal:** Review Terraform code consistently.

Initial checks:

- [ ] Required Terraform version constraints.
- [ ] Provider version constraints.
- [ ] Missing variable descriptions.
- [ ] Missing variable validation where appropriate.
- [ ] Required tags.
- [ ] Naming conventions.
- [ ] Basic module structure rules.
- [ ] Formatting compliance.
- [ ] Terraform validation.
- [ ] Optional TFLint and Trivy integrations.

For every rule, record:

- Rule ID.
- Severity.
- File and line, where available.
- Evidence.
- Why the rule matters.
- Recommended remediation.
- Whether the finding is mandatory or advisory.

Avoid writing a replacement for a mature linter. Use our effort on integration, prioritization, and useful explanations.

**Exit criteria:** Each rule has a positive test, a negative test, and a clear explanation.

### Phase 4 — Add safe, verified refactoring

**Goal:** Propose infrastructure refactors and test their consequences.

Start with two cases:

1. Renaming a resource while preserving its identity through an appropriate `moved` block.
2. Refactoring `count` to `for_each` while preserving the intended resource addresses.

Tasks:

- [ ] Identify the original and intended addresses.
- [ ] Generate a proposed patch or separate output file.
- [ ] Show the complete diff before any change is applied.
- [ ] Require explicit user approval before modifying a working copy.
- [ ] Run appropriate syntax and validation checks.
- [ ] Compare the resulting plan with the expected behavior.
- [ ] Report unexpected creation, replacement, or destruction.
- [ ] Never automatically apply the plan.

A clean plan is not sufficient proof on its own. A refactor may legitimately change infrastructure, and an empty plan is not always the desired result. Verification must compare the actual result with the expected change.

**Exit criteria:** Tests prove that intended resource identity is preserved in the supported examples and that unexpected destructive changes cause verification to fail.

### Phase 5 — Add local plan history

**Goal:** Make recurring problems visible across runs.

Build this after the first single-plan replacement analyzer works.

Initial history fields:

- Schema version.
- Timestamp.
- Terraform version.
- Plan JSON format version.
- Resource address.
- Resource type.
- Action.
- Replacement attribute paths.
- Approved action-reason metadata, where useful.

Do not store raw plans, resource attribute values, environment variables, state files, or credentials.

Tasks:

- [ ] Create a versioned local history format.
- [ ] Add a retention and deletion policy.
- [ ] Support listing previous runs.
- [ ] Compare repeated replacement findings.
- [ ] Detect recurring replacement paths.
- [ ] Correlate changes over time without overstating causality.
- [ ] Handle resource renames and deleted resources.
- [ ] Make history corruption recoverable.
- [ ] Add tests for migration between history schema versions.

**Exit criteria:** Given several synthetic runs, the tool identifies repeated replacements and accurately distinguishes recurrence from a proven root cause.

### Phase 6 — Import and permission assistance

**Goal:** Help engineers bring manually created resources under Terraform and identify risky permissions.

Tasks:

- [ ] Generate starter import blocks from explicitly supplied resource information.
- [ ] Generate starter resource configuration where the inputs are sufficient.
- [ ] Flag wildcard IAM actions and resources.
- [ ] Flag overly permissive network rules.
- [ ] Provide remediation suggestions with evidence.
- [ ] Avoid claiming a permission is exploitable based solely on a wildcard.
- [ ] Keep generated code separate until the user approves it.

**Exit criteria:** Generated import configurations and permission findings are tested against representative examples.

### Phase 7 — Drift and upgrade assistance

**Goal:** Explain configuration drift and version-related problems.

Tasks:

- [ ] Accept a refresh-only plan generated by the user.
- [ ] Separate planned configuration changes from detected remote changes where the plan supports that distinction.
- [ ] Explain likely drift causes without assuming who made a change.
- [ ] Detect deprecated arguments and known provider migration issues.
- [ ] Compare Terraform and OpenTofu behavior where supported.
- [ ] Maintain a tested compatibility matrix.

Do not build direct AWS access into this phase by default. Start with plans the user explicitly generates.

**Exit criteria:** The tool explains supported drift and upgrade cases using test fixtures and clearly reports unknown cases.

### Phase 8 — Team and paid features

**Goal:** Validate whether the product can become a business.

Potential features:

- [ ] Shared standards.
- [ ] Pull-request comments.
- [ ] Team-level history.
- [ ] Centralized reports.
- [ ] Policy enforcement.
- [ ] Optional hosted AI explanations.

Keep the core local CLI free initially. Validate actual demand before investing in a hosted service.

**Exit criteria:** Real users repeatedly use the product, identify measurable value, and at least some demonstrate willingness to pay for a specific team feature.

---

## 5. Security design — mandatory from day one

This is not a feature to add later.

### Important technical distinction

Terraform plan JSON can contain sensitive values. A parser that loads the JSON processes the original document in memory, even if it never writes those values to a report.

Therefore, the honest security promise is:

- No network transmission in the core CLI.
- No persistence of raw plans or attribute values.
- No printing of attribute values.
- No telemetry by default.
- Only allowlisted metadata enters findings and reports.
- Optional AI receives only a deliberately constructed, reviewed payload.

Do not claim that the tool never reads a secret value if it loads the complete plan JSON.

### Security requirements

- [ ] Never serialize raw Terraform change objects into reports.
- [ ] Use allowlists rather than trying to enumerate every possible secret field.
- [ ] Never log the input document or exception data that could expose it.
- [ ] Test that synthetic secret markers never appear in reports, history, or AI payloads.
- [ ] Treat resource addresses and attribute names as potentially sensitive metadata.
- [ ] Never commit real plan JSON or Terraform state.
- [ ] Do not automatically run Terraform commands that could access remote backends without explicit user action.
- [ ] Keep AI credentials in environment variables or an appropriate secret store.
- [ ] Do not store API keys in configuration files, logs, or Git.
- [ ] Make AI calls opt-in and display what information will be sent.
- [ ] Never run apply or destroy.

---

## 6. Testing strategy

Use synthetic infrastructure. Do not deploy to AWS merely to prove the first CLI works.

Create fixtures using local, random, null, and time providers where appropriate. These are useful for exercising Terraform behavior without needing production infrastructure.

### Required test categories

1. **Unit tests:** Individual parsers, analyzers, and report renderers.
2. **Golden tests:** Known input plans produce expected findings.
3. **Regression tests:** Every fixed bug becomes a test.
4. **Security tests:** Secret markers never appear in output or persisted records.
5. **Malformed-input tests:** Invalid JSON, incomplete objects, unknown actions, and unsupported versions.
6. **Integration tests:** Real Terraform-generated plans from synthetic projects.
7. **Cross-platform tests:** macOS, Linux, and Windows.
8. **Compatibility tests:** Explicitly supported Terraform and OpenTofu versions.
9. **Fix verification tests:** Expected changes pass; unexpected destructive changes fail.

Every bug discovered by Copilot or ChatGPT must result in a regression test when practical.

---

## 7. How to use GitHub Copilot and ChatGPT

### GitHub Copilot: implementation

Give Copilot one bounded task at a time.

For every task:

1. Explain the feature and its constraints.
2. Ask Copilot to inspect the existing repository before coding.
3. Provide acceptance criteria.
4. Ask it to implement the smallest change possible.
5. Require automated tests.
6. Ask it to summarize changed files and design choices.
7. Review the diff.
8. Run tests and inspect failures.
9. Commit the change only when the acceptance criteria pass.

Do not ask Copilot to build all eight phases in one prompt.

### ChatGPT: independent review

Bring me:

- The relevant source files or Git diff.
- Test output.
- The intended behavior.
- Any failing examples.
- Your questions or concerns.

I will review architecture, correctness, test coverage, security boundaries, Terraform semantics, and maintainability. I can also help debug failures and refine the implementation.

Never paste real credentials, production state, raw sensitive plans, or private employer code into a review.

### Git workflow

Use a branch per feature, such as:

- `feature/plan-summary`
- `feature/replacement-analysis`
- `feature/standards-review`
- `feature/verified-refactor`

Keep commits small. This makes regressions easier to isolate and roll back.

---

## 8. Definition of done for every feature

A feature is not complete merely because Copilot generated code that runs once.

It is complete only when:

- [ ] Requirements and acceptance criteria are written.
- [ ] Expected behavior is covered by automated tests.
- [ ] Negative and malformed inputs are tested.
- [ ] Security implications are reviewed.
- [ ] Findings contain evidence.
- [ ] Unknown cases are handled honestly.
- [ ] No unexpected files are modified.
- [ ] Documentation is updated.
- [ ] The full existing test suite passes.
- [ ] The diff has been reviewed.
- [ ] The feature works without AI if it is part of the deterministic core.

---

## 9. Product validation and launch

Do not wait until every planned feature exists before showing the product.

### Early validation

- [ ] Test it on synthetic plans you understand.
- [ ] Compare its output with Terraform's own plan output.
- [ ] Install and evaluate existing tools against the same examples.
- [ ] Document where tfwhy offers a genuinely better workflow.
- [ ] Record false positives and unsupported cases.
- [ ] Share a demonstration using synthetic infrastructure.

### Initial success measures

These are proposed targets, not evidence of product-market fit:

- A working version is released with installation instructions.
- At least 10 people outside your immediate team try it.
- At least 8 out of 10 representative test projects pass the verified-fix acceptance criteria on the first attempt.
- At least 3 users return to use it again without prompting.
- Every reported security or destructive-action bug is investigated and covered by a regression test where possible.

Measure repeat use and trust, not just downloads or social-media engagement.

---

## 10. First two weeks: execution checklist

### Week 1 — Reliable foundation

- [ ] Day 1: Set up Git, Python environment, and project conventions.
- [ ] Day 2: Review the existing starter and make the tests reproducible.
- [ ] Day 3: Expand synthetic plan fixtures.
- [ ] Day 4: Finish plan summary and replacement reporting.
- [ ] Day 5: Test all report formats and privacy boundaries.
- [ ] Weekend: Compare output against Terraform and review existing tools.

### Week 2 — First differentiating capability

- [ ] Day 1: Define the replacement-finding schema.
- [ ] Day 2: Parse replacement paths and action reasons.
- [ ] Day 3: Associate paths with available HCL expressions.
- [ ] Day 4: Add evidence, uncertainty handling, and regression tests.
- [ ] Day 5: Run the full test suite and fix defects.
- [ ] Weekend: Record a short demonstration using synthetic plans and document limitations.

Adjust the schedule to your available hours. Passing the quality gates matters more than finishing on a specific date.

---

## 11. Decisions to postpone

Do not spend early development time on:

- A final brand name and logo.
- A hosted dashboard.
- Direct cloud account integrations.
- Automatic Terraform execution.
- A custom pricing engine.
- A proprietary scanner for checks existing tools already perform.
- A complex agent framework.
- Enterprise authentication and billing before demand is validated.

Focus on the CLI, replacement analysis, standards, and verified fixes first.

---

## 12. Immediate next action

Start by reviewing the existing starter repository and making sure its baseline tests pass.

Then implement **Phase 1: Plan Explainer**. Do not start the history database, hosted AI, or refactoring engine yet.

Once Phase 1 is reliable, build the replacement-cause analyzer and its evidence model. That is where the product begins to distinguish itself.

**Working principle:** Copilot writes the implementation; tests establish behavior; independent review challenges assumptions; the user approves every consequential change.
