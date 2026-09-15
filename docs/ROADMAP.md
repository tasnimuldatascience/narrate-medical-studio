# Production roadmap

The current release proves a complete local authoring and draft-render workflow. Production readiness requires measured reliability, clinical governance, deployment hardening, and practitioner usability evidence.

## Priority 1: trustworthy medical review

- Build a permission-cleared, practitioner-labelled dataset covering at least six specialties and varied text, notes, image, table, unit, negation, sequence, and source-conflict cases.
- Keep prompt-development examples separate from held-out evaluation presentations.
- Measure false findings, missed findings, parse failures, abstentions, correction time, and results by error type.
- Add adjudication for reviewer/model disagreements.
- Keep automatic medical rewriting disabled.

**Release evidence:** predefined acceptable false-positive and false-negative thresholds on held-out decks, with sample sizes and practitioner adjudication published internally.

## Priority 2: pronunciation and timing

- Add a versioned medical pronunciation dictionary with project overrides and audio previews.
- Evaluate drugs, anatomy, procedures, abbreviations, and numbers with practitioners.
- Add forced alignment only if word-level caption synchronization is required.
- Bind pronunciation and timing decisions to the exact narration and voice recipe.

**Release evidence:** documented listening evaluation, no unresolved critical pronunciation defects in released lessons, and measured caption alignment for any claimed timing precision.

## Priority 3: durable execution

- Replace the single JSON project job record with normalized runs, stages, attempts, artifacts, and review records.
- Add worker leases, fencing, bounded retries, disk quotas, and restart recovery.
- Preserve immutable artifact hashes and publish through an atomic manifest pointer.
- Test cancellation and failure at every stage boundary.

**Release evidence:** repeated fault-injection runs produce no partial, stale, cross-project, or unapproved publications; completed matching checkpoints resume after restart.

## Priority 4: practitioner-grade review and identity

- Add authenticated users and signed, revision-bound review records.
- Separate source transcription, script, assessment, visual plan, pronunciation, final preview, and release decisions.
- Add undoable authoring history and explicit resolution for source conflicts and reviewer findings.
- Run keyboard, screen-reader, and contrast testing across critical tasks.

**Release evidence:** representative practitioners complete import, correction, authoring, review, and export without critical usability or accessibility blockers.

## Priority 5: richer educational visuals

- Add evidence-linked reusable scene patterns, annotations, step diagrams, and accessible image descriptions.
- Keep every clinical visual change reviewable and reversible.
- Add visual regression checks for labels, captions, source completeness, and region geometry.
- Validate any generated imagery separately before allowing it in a medical lesson.

**Release evidence:** every visual element has source/provenance metadata and practitioner approval; no silent crop or truncation in the supported fixture set.

## Priority 6: packaging and operations

- Produce a signed Windows installer with pinned assets, license inventory, checksums, update, rollback, backup, and uninstall behavior.
- Build a complete offline installation bundle.
- Add process-level network restrictions or document the required OS policy.
- Add optional encrypted storage and organization-managed retention.
- Validate supported PowerPoint and browser versions on clean machines.

**Release evidence:** a clean workstation completes install, import, authoring, rendering, playback, update, rollback, and recovery with network egress denied.

## Later product expansion

- SCORM/xAPI and LMS validation
- multilingual narration and pronunciation evaluation
- team collaboration and review queues
- reusable lesson templates and learning objectives
- validated macOS/Linux support
- organization policy packs and audit export

Each expansion needs its own acceptance evidence. It should not inherit medical, platform, or deployment claims from the Windows development workflow.

## Release gates

A production release requires all of the following:

1. Pinned dependencies and required automated checks pass.
2. Supported file types and workstation profiles pass compatibility testing.
3. The evaluator meets agreed held-out reliability thresholds while remaining advisory.
4. Every released slide has valid source, script, visual, assessment, pronunciation, and final-artifact review.
5. No stale, cancelled, incomplete, or unapproved revision can be published.
6. The workflow passes under denied network egress.
7. Critical author and learner paths pass accessibility and usability review.
8. A clean-machine installer, update, rollback, backup, and recovery test succeeds.
9. Dependency and model redistribution terms are approved.
10. No known critical defect remains in the declared supported workflow.

Until these gates are met, the correct label is **development release for supervised private authoring**.
