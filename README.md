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

For an install-once workflow from a published package, use `pipx` after a package is published:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install tfwhy  # requires a published package
```

For this local checkout or any unreleased development version, install directly from the repository:

```bash
pipx install .
```

Alternatively, use an editable virtual-environment install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The package currently has no declared license. Treat it as unreleased project code until a license decision is made; no open-source license is implied.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
tfwhy --help
```

The console command works from outside the checkout after installation. The full test suite can be run with `python -m unittest discover -s tests -v`.

## Repository Layout

```text
src/tfwhy/                         Python package and CLI
tests/                             Unit, integration, and privacy tests
tests/fixtures/corporate_project/  Provider-free module test project
tests/fixtures/aws_scanner/       AWS-only static security-review fixture
.github/workflows/                 Continuous integration
```

Terraform projects under `tests/fixtures/` are test inputs only. They must not be applied to real infrastructure.

## Run From a Terraform Project

After installation, change to any Terraform project directory and run:

```bash
tfwhy review
tfwhy review --format json
tfwhy explain ./tfplan.json --dir .
tfwhy drift ./tfplan.json
```

Use `--dir PATH` when the configuration is elsewhere. `explain` always requires an explicit plan path; TFWhy does not guess which plan to use. History is opt-in and defaults to `~/.tfwhy/history.json`, never the Terraform project directory. Use `--history-file PATH` for an explicit alternate location.

### Upgrade and troubleshooting

```bash
pipx upgrade tfwhy       # published-package installs
pipx uninstall tfwhy
python -m unittest discover -s tests -v
```

If `tfwhy` is not found after a `pipx` install, reopen the shell or ensure the pipx bin directory is on `PATH`. `pipx install tfwhy` is not currently verifiable because no PyPI release exists; use `pipx install .` from this checkout. Terraform is optional for plan explanation; `review` reports Terraform formatting/validation as unavailable when the executable is absent. AWS credentials are not required for offline plan JSON analysis.

## Offline Terraform plan fixture

The AWS fixture at `tests/fixtures/aws_scanner/main.tf` is intended for static scanner testing and does not provide credentials. For a complicated corporate-style plan JSON without AWS access, use the provider-free `tests/fixtures/corporate_project/infra/modules/dev` fixture:

```bash
cd tests/fixtures/corporate_project
terraform -chdir=infra init -backend=false
terraform -chdir=infra plan -out=/tmp/tfwhy-corporate.tfplan
terraform -chdir=infra show -json /tmp/tfwhy-corporate.tfplan > tfplan.json
tfwhy explain tfplan.json --dir ./infra
tfwhy review --dir ./infra
```

It uses Terraform's built-in `terraform_data` resource and the local `random` provider, and creates no cloud resources. The generated `tfplan.json` is ignored by Git. Run `terraform show` with `-chdir=infra` so Terraform can load the provider initialized for that configuration.

## Usage

```bash
tfwhy explain plan.json
tfwhy explain plan.json --format markdown
tfwhy explain plan.json --format json
tfwhy explain plan.json --dir ./infra
tfwhy drift plan.json
tfwhy drift plan.json --format json
tfwhy review --dir ./infra
tfwhy review --dir ./infra --required-tag Environment --skip-rule TFWHY-SEC-002
tfwhy import --address aws_s3_bucket.logs --id example-logs --starter-config
tfwhy import --address aws_s3_bucket.logs --id example-logs --starter-config --out ./tfwhy-import.tf --apply --approve
tfwhy fix --finding TFWHY-001 --plan plan.json --dir ./infra --dry-run
tfwhy verify --plan after-change-plan.json --from aws_instance.old --to aws_instance.new --kind resource_rename
tfwhy explain plan.json --save-history
tfwhy history
tfwhy history show 1
tfwhy history clear --confirm
```

The current implementation supports Terraform plan JSON format versions with major version `1` and a numeric `MINOR` component, such as `1.0` and newer compatible `1.x` versions. It rejects malformed versions and unsupported major versions, such as `2.0`; accepting a newer minor version does not claim support for a different major version. It reports create, update, delete, replacement, read, and no-op resources, including addresses, types, replacement paths, and supported action reasons: `replace_because_cannot_update`, `replace_because_tainted`, `replace_by_request`, `delete_because_no_move`, `read_because_config_unknown`, `read_because_dependency_pending`, and `read_because_deferred`.

| Compatibility surface | Exercised support | Boundary |
| --- | --- | --- |
| Plan JSON format | `1.0`, `1.1`, and other numeric `1.x` minors | Major versions other than `1` are rejected. |
| Terraform version metadata | Synthetic `1.6.0` and `1.9.0` metadata | The version is reported, not evaluated for provider behavior. |
| Remote-drift metadata | Optional `resource_drift` and structural `relevant_attributes` in format `1.x` | Ordinary `resource_changes` are never inferred to be remote drift. |
| Configuration evidence | Root module and literal local child-module sources under `--dir` | Remote, computed, and local sources outside `--dir` remain inconclusive. |

Replacement paths are evidence supplied by Terraform; `tfwhy` does not infer a root cause from them. Unknown action reasons are omitted rather than presented as supported evidence. Invalid JSON, unsupported versions, missing required fields, and malformed resource changes produce an error and non-zero exit status.

## Drift assistance

`tfwhy drift PLAN.json` is a local reader for Terraform's optional `resource_drift` plan metadata. It never refreshes state, queries a provider, accesses a cloud account, or needs credentials. The same safe drift findings also appear in `tfwhy explain` output, after the separate list of planned resource changes.

Terraform can report a resource in both `resource_changes` and `resource_drift`. TFWhy reports that overlap and any structural `relevant_attributes` paths as correlation only: neither proves that drift caused a planned action, who changed a remote object, or that the plan was generated with `terraform plan -refresh-only`. Terraform's JSON plan format has no supported refresh-only-mode marker that TFWhy relies on. If `resource_drift` is absent, TFWhy reports no detected remote drift rather than guessing from normal actions. Raw before/after values are not retained or rendered.

The supported drift path is a user-generated plan that Terraform has already produced, including refresh-only plans when their JSON contains `resource_drift`. OpenTofu behavior is not claimed or specially handled because this repository has no reproduced OpenTofu JSON compatibility case.

## Security and limitations

Reports and CLI errors contain only an explicit allowlist of plan metadata and safe structural diagnostics. They never include Terraform before/after values, sensitive values, complete change objects, or raw plan content. Terraform plan JSON can itself contain sensitive data, so reading a plan necessarily processes that input in memory. The core CLI makes no network calls and never runs `terraform apply` or `terraform destroy`.

This release does not fully evaluate Terraform configuration, resolve arbitrary modules or variables, determine replacement root causes conclusively, run Terraform validation outside the Phase 3 review command, or verify fixes. The configuration scanner only inspects bounded, conservative evidence.

## Replacement-cause analysis

When a replacement is present, `tfwhy` emits a replacement finding with the resource address and type, Terraform's replacement paths, safe evidence, an explanation, and one of three confidence categories:

- **Confirmed** means Terraform directly supplied a cause-specific reason such as taint or an explicit replacement request. Generic replacement metadata, provider replacement requirements, and address changes alone do not confirm an upstream root cause.
- **Likely** means an optional configuration directory contains a matching resource block and a recognizable timestamp, random-value, AMI/data-source, `user_data`, `count`, or `for_each` pattern.
- **Unknown** means the plan or available configuration does not provide enough evidence to identify an upstream cause. A replacement path alone is never treated as proof of that cause.

Configuration inspection is a small, dependency-free, HCL-aware scanner. It matches the complete resource address (after removing instance indexes), including literal local child-module sources beneath `--dir`; resources with the same type and name in different modules are not cross-matched. It records only relative file paths, line numbers, attribute names, and recognized pattern labels. For a direct, single-line expression it can link an attribute to a variable default, local, data source, or managed-resource declaration and report the relevant source locations. A data source or dynamic timestamp/random expression is only a possible cause; a managed-resource reference is evidence of a link, not proof that its value changed.

The scanner is not a Terraform language evaluator and deliberately has no HCL-parser dependency. Conditional and multiline expressions, functions other than the recognized dynamic patterns, computed defaults, module outputs, remote or computed module sources, local modules outside `--dir`, generated configuration, and indirect dependency graphs remain **Unknown**. `count`, `for_each`, indexed addresses, and `moved` blocks are recorded only as contextual metadata and never establish a replacement cause. Terraform behavior, state, and before/after values are not evaluated or exposed.

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
- `TFWHY-IAM-001`, `TFWHY-IAM-002`: statically visible IAM Allow action or resource wildcards.
- `TFWHY-NET-002`: unrestricted all-protocol security-group egress.
- `TFWHY-NET-003`: public network-ACL SSH/RDP or all-protocol ingress.
- `TFWHY-UPGRADE-001`: literal `hashicorp/terraform` provider source, which HashiCorp documents as legacy and incompatible with Terraform 0.11 and later.
- `TFWHY-FMT-001`, `TFWHY-VALIDATE-001`: Terraform formatting or validation failed.
- `TFWHY-TOOL-001`: Terraform is unavailable, so Terraform-dependent checks were skipped; this is informational, not a security finding.
- `TFWHY-CONFIG-001`: configuration file could not be safely scanned.

Formatting uses `terraform fmt -check -recursive`; validation uses `terraform validate -no-color`. These commands never apply or destroy infrastructure. If Terraform is not installed, the review reports an informational unavailable-tool finding. TFLint, Trivy, cloud APIs, network calls, and telemetry are not required or used.

The security checks are intentionally narrow and high-confidence. They cover unrestricted IPv4/IPv6 security-group ingress, including direct references to literal variable defaults; all-protocol unrestricted security-group egress; statically visible public network-ACL SSH/RDP or all-protocol ingress; missing explicit encryption settings for selected AWS storage resources; and literal IAM `Allow` statements with global or service action wildcards or a global resource wildcard. These findings identify potentially broad permissions, not reachability or exploitability. They are not a comprehensive AWS, Terraform, or policy security scanner. Complex HCL, computed tags, provider defaults, modules, indirect expressions, IAM policy documents outside supported `jsonencode` literals, and unsupported resource types may remain unreported or require manual review.

The upgrade check is intentionally a single, source-backed migration rule: it recognizes only a literal line declaring `source = "hashicorp/terraform"` within `required_providers`. Its remediation is to remove that legacy requirement and review use of Terraform's built-in provider features; it does not rewrite configuration or infer a provider-version upgrade path. Comments, computed sources, arbitrary deprecated arguments, provider schemas, and OpenTofu-specific migrations remain unsupported. See HashiCorp's [provider requirements documentation](https://developer.hashicorp.com/terraform/language/providers/requirements) for the legacy-provider compatibility statement.

## Import proposals

`tfwhy import` creates a reviewable Terraform `import` block only from the address and identifier you explicitly provide. It never queries a cloud account, state file, or provider API.

```bash
# Preview a unified diff; no file is written.
tfwhy import --address aws_s3_bucket.logs --id example-logs --starter-config

# Writing requires a new, explicit path plus both approval flags.
tfwhy import --address aws_s3_bucket.logs --id example-logs --starter-config \
  --out ./tfwhy-import.tf --apply --approve
```

The initial starter-configuration support is intentionally limited to a root, unindexed `aws_s3_bucket`: its supplied import ID is its bucket name. Other supported managed-resource addresses receive an import block but no guessed resource body; the report explains that provider-specific required arguments are missing. Module instances, `count`/`for_each` targets, data sources, malformed addresses, cloud discovery, state inspection, and arbitrary provider schemas are unsupported. The import identifier appears only in the user-requested generated diff or file and is never saved to history; avoid placing secrets in an import identifier.

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
