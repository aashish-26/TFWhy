# tfwhy

`tfwhy` is a local-first, deterministic Terraform plan explainer. Phase 1 reads Terraform plan JSON and reports resource actions without sending data over the network or requiring AI credentials.

## Installation

Requires Python 3.11 or newer. From a checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

No runtime dependency or cloud credential is required.

The package currently has no declared license. Treat it as unreleased project code until a license decision is made; no open-source license is implied.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
tfwhy --help
```

The console command works from outside the checkout after installation. The full test suite can be run with `python -m unittest discover -s tests -v`.

## Usage

```bash
tfwhy explain plan.json
tfwhy explain plan.json --format markdown
tfwhy explain plan.json --format json
tfwhy explain plan.json --dir ./infra
tfwhy review --dir ./infra
tfwhy review --dir ./infra --required-tag Environment --skip-rule TFWHY-SEC-002
tfwhy fix --finding TFWHY-001 --plan plan.json --dir ./infra --dry-run
tfwhy verify --plan after-change-plan.json --from aws_instance.old --to aws_instance.new --kind resource_rename
tfwhy explain plan.json --save-history
tfwhy history
tfwhy history show 1
tfwhy history clear --confirm
```

The current implementation supports Terraform plan JSON format versions with major version `1` and a numeric `MINOR` component, such as `1.0` and newer compatible `1.x` versions. It rejects malformed versions and unsupported major versions, such as `2.0`; accepting a newer minor version does not claim support for a different major version. It reports create, update, delete, replacement, read, and no-op resources, including addresses, types, replacement paths, and supported action reasons: `replace_because_cannot_update`, `replace_because_tainted`, `replace_by_request`, `delete_because_no_move`, `read_because_config_unknown`, `read_because_dependency_pending`, and `read_because_deferred`.

Replacement paths are evidence supplied by Terraform; `tfwhy` does not infer a root cause from them. Unknown action reasons are omitted rather than presented as supported evidence. Invalid JSON, unsupported versions, missing required fields, and malformed resource changes produce an error and non-zero exit status.

## Security and limitations

Reports and CLI errors contain only an explicit allowlist of plan metadata and safe structural diagnostics. They never include Terraform before/after values, sensitive values, complete change objects, or raw plan content. Terraform plan JSON can itself contain sensitive data, so reading a plan necessarily processes that input in memory. The core CLI makes no network calls and never runs `terraform apply` or `terraform destroy`.

This release does not fully evaluate Terraform configuration, resolve modules or variables, determine replacement root causes conclusively, run Terraform validation outside the Phase 3 review command, or verify fixes. The optional Phase 2 scanner only inspects conservative configuration evidence.

## Replacement-cause analysis

When a replacement is present, `tfwhy` emits a replacement finding with the resource address and type, Terraform's replacement paths, safe evidence, an explanation, and one of three confidence categories:

- **Confirmed** means Terraform directly supplied a cause-specific reason such as taint or an explicit replacement request. Generic replacement metadata, provider replacement requirements, and address changes alone do not confirm an upstream root cause.
- **Likely** means an optional configuration directory contains a matching resource block and a recognizable timestamp, random-value, AMI/data-source, `user_data`, `count`, or `for_each` pattern.
- **Unknown** means the plan or available configuration does not provide enough evidence to identify an upstream cause. A replacement path alone is never treated as proof of that cause.

Configuration inspection is a small, dependency-free scanner for unambiguous root-module `resource` blocks in top-level `.tf` files. Module-addressed resources and duplicate type/name matches deliberately remain **Unknown**. It records only relative file paths, line numbers, attribute names, and recognized pattern labels. It does not evaluate HCL, resolve variables or modules, compare before/after values, inspect state, or prove that an expression changed. Complex HCL, generated configuration, moved blocks, provider behavior, and indirect dependencies may therefore remain **Unknown**.

## Standards and security review

Phase 3 adds the deterministic `review` command. Reports are available in terminal, Markdown, and JSON formats:

```bash
tfwhy review --dir ./infra
tfwhy review --dir ./infra --format json
```

The default required tag is `Name` for supported AWS resources. Use repeated `--required-tag TAG` options to replace that default policy, and repeated `--skip-rule RULE_ID` options to disable applicable checks.

Current rule IDs include:

- `TFWHY-TF-001`, `TFWHY-TF-002`: Terraform version constraint missing or unbounded.
- `TFWHY-PROVIDER-001`, `TFWHY-PROVIDER-002`: provider constraints missing or unbounded.
- `TFWHY-TAG-001`: required AWS resource tag missing.
- `TFWHY-DOC-001`: variable or output description missing.
- `TFWHY-NAME-001`: basic lowercase snake_case naming violation.
- `TFWHY-SEC-001`: public security-group ingress detected.
- `TFWHY-SEC-002`: supported storage resource lacks explicit encryption configuration.
- `TFWHY-FMT-001`, `TFWHY-VALIDATE-001`: Terraform formatting or validation failed.
- `TFWHY-TOOL-001`: Terraform is unavailable, so Terraform-dependent checks were skipped; this is informational, not a security finding.
- `TFWHY-CONFIG-001`: configuration file could not be safely scanned.

Formatting uses `terraform fmt -check -recursive`; validation uses `terraform validate -no-color`. These commands never apply or destroy infrastructure. If Terraform is not installed, the review reports an informational unavailable-tool finding. TFLint, Trivy, cloud APIs, network calls, and telemetry are not required or used.

The security checks are intentionally narrow and high-confidence. They cover unrestricted IPv4/IPv6 security-group ingress and missing explicit encryption settings for selected AWS storage resources. They are not a comprehensive AWS, Terraform, or policy security scanner. Complex HCL, computed tags, provider defaults, modules, indirect expressions, and unsupported resource types may remain unreported or require manual review.

## Local plan history

History is disabled by default. Save sanitized metadata only when explicitly requested:

```bash
tfwhy explain plan.json --save-history
tfwhy explain plan.json --save-history --history-file ./tfwhy-history.json
tfwhy history
tfwhy history show 1 --format json
tfwhy history clear --confirm
```

The default history file is `~/.tfwhy/history.json`; `--history-file` overrides it. Entries contain a schema version, timestamp, Terraform/plan format versions, action counts, and allowlisted resource metadata: address, type, action, replacement paths, and supported action reasons. Raw plan JSON, state, before/after values, configuration expressions, credentials, and secrets are never persisted. Corrupt or unsupported history files are reported without being overwritten. Clearing history requires `--confirm` and deletes only the selected local history file.

History can identify repeated replacement metadata such as the same address and replacement paths across saved runs. Recurrence is an observation, not proof of a root cause or evidence that the same upstream configuration expression caused every occurrence.

## Verified refactoring

Phase 4 supports conservative, plan-driven proposals:

```bash
tfwhy fix --finding TFWHY-001 --plan plan.json --dir ./infra --dry-run
tfwhy fix --finding TFWHY-001 --plan plan.json --dir ./infra --apply --approve
tfwhy verify --plan after-change-plan.json --from aws_instance.old --to aws_instance.new --kind resource_rename
```

Fix IDs are ordinal within the replacement resources in the supplied plan (`TFWHY-001` is the first replacement). Dry-run is the default and emits a proposed `moved.tf` unified diff without writing files. Writing requires both `--apply` and explicit `--approve`; an existing `moved.tf` is never overwritten. The command never runs `terraform apply` or `terraform destroy` and never changes Terraform state.

The initial proposal scope is an unambiguous root-level resource rename or a single numeric-to-string instance mapping that supports a `count` to `for_each` migration. Ambiguous, module-addressed, unsupported, or value-dependent mappings produce no fix. Verification consumes a user-generated plan and reports `verified` only when the target address is `no-op` and the old address is absent; otherwise it reports `not_verified` or `inconclusive`. A clean plan by itself is not considered proof of success.

## Tests

Run the dependency-free test suite with:

```bash
python -m unittest discover -s tests -v
```

## MVP scope

- Deterministic Terraform plan summaries in terminal, Markdown, and JSON.
- Conservative replacement-cause evidence without AI or cloud access.
- Local standards and narrow AWS security checks.
- Dry-run Terraform refactoring proposals with explicit approval for writes.
- Opt-in, sanitized local plan history with recurrence observations.

Plan JSON, Terraform state, variable files, credentials, and sensitive configuration should never be committed. Terraform plan JSON may contain sensitive data and is processed in memory; TFWhy does not transmit it or persist raw plan values.
