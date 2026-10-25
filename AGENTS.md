# Repository instructions

This repository contains firmware for a real telescope device. Treat changes as production code that can affect connected hardware.

## Scope and delivery

- Keep each pull request focused on one issue or clearly related change.
- Finish the implementation before opening a pull request. Do not leave TODO-only changes, placeholder code, or unfinished stubs.
- Preserve existing behavior unless the requested change requires otherwise.
- Do not claim hardware behavior is verified unless it was tested on the device. State any remaining verification limits clearly.

## Implementation

- Read the relevant code and surrounding conventions before editing.
- Prefer small, complete changes that fit the existing architecture.
- Handle errors and cleanup explicitly, especially around hardware connections, motion, and process shutdown.
- Avoid speculative abstractions and unrelated refactors.
- Keep documentation and user-facing text concise and specific.

## Writing like a shipped product, not a draft

This is production firmware for a real device, not a demo or a sandbox. PR descriptions, commit messages, code comments, and docs should read that way:

- No AI-slop: no padded summaries, no restating the diff in prose, no emoji-heavy section headers, no "comprehensive/robust/seamless" filler adjectives. Say what changed and why in as few sentences as actually carry signal.
- No long docs for short changes. A one-file config fix gets a few sentences, not a written-up rationale with headings.
- No unfinished-looking output: no "TODO later", no placeholder sections, no hedging language about whether something works -- verify it, then state it plainly.
- If a generated file (README, this file, a workflow comment) starts accumulating restated obvious comments or got longer than the code it describes, trim it as part of the change instead of adding on top.

## Release labels

`.github/release-drafter.yml` groups the draft release by label. The autolabeler only fires on recognized title/branch patterns, so a PR whose title doesn't match lands unlabeled and falls into the uncategorized list, and the version bump defaults to patch. Before opening a PR, apply exactly one of these labels yourself if the title doesn't already match an autolabeler rule:

- `enhancement` -- new functionality, including tooling/process additions. Bumps the next version as minor.
- `bug` -- a correctness fix.
- `documentation` -- docs-only, no code.
- `dependencies` -- dependency version bumps (usually applied automatically by Dependabot).

Never leave a merged PR unlabeled; it silently drops out of the changelog sections.

## Verification

- Run the relevant existing checks for changed code when practical.
- Do not run all cca 2000 tests 2 times when not necessary.
- Review the final diff for correctness, unintended changes, and whitespace errors.
- Report what was checked and any checks that could not be run.

## Other instructions
When you spot e.g. some TODO or smillar notice in code, file a GitHub issue for it immediately.
