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

## Verification

- Run the relevant existing checks for changed code when practical.
- Review the final diff for correctness, unintended changes, and whitespace errors.
- Report what was checked and any checks that could not be run.
