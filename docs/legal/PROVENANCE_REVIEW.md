# Copyright and provenance review

> Initial review record only. GitHub contributor metadata is not a complete copyright audit.

## Current observed repository signals

At the start of the transition review, GitHub's contributor endpoint identified:

- `nightcrawlerxme` as the only listed human contributor; and
- `dependabot[bot]` as an automated contributor.

Recent commits also contain AI-tool co-author text. AI-tool attribution is not treated as a human copyright assignment, but AI-assisted changes still require normal provenance and similarity review.

## Required author inventory

- [ ] Export all commit author and committer identities across the complete history.
- [ ] Export merged pull-request authors and reviewers.
- [ ] Identify co-author trailers and any human identities hidden by squash merges.
- [ ] Identify work produced by employees, contractors, advisors, partners, or customers.
- [ ] Confirm the relationship between `nightcrawlerxme`, WAIT, and the legal copyright owner.
- [ ] Record written assignment or sufficient relicensing permission for each material human contribution.

## Source provenance

- [ ] Search for copied or adapted code, documentation, schemas, examples, images, and configuration from external projects.
- [ ] Review generated and AI-assisted changes for materially reproduced third-party expression.
- [ ] Verify all snippets, templates, sample data, screenshots, icons, and media rights.
- [ ] Complete a secret-history scan before moving private WAIT-Sync history or files.
- [ ] Classify every proposed WAIT-Sync migration item as public interface, public baseline, commercial pack, shared schema, third-party review, IP review, or secret-history review.

## Dependency inventory

- [ ] Python direct and transitive dependencies.
- [ ] JavaScript direct and transitive dependencies.
- [ ] Rust/Cargo direct and transitive dependencies.
- [ ] Container base images and system packages.
- [ ] Desktop bundling/runtime components.
- [ ] Optional model, vector, document-processing, and connector dependencies.
- [ ] Fonts, icons, images, demo data, and generated reports.

## Required outputs

- [ ] Approved contributor/copyright register.
- [ ] Dependency license report.
- [ ] Third-party notices.
- [ ] Reproducible SBOM.
- [ ] List of components excluded from commercial relicensing, if any.
- [ ] List of components requiring replacement, permission, or separate distribution.
- [ ] Counsel approval to proceed with dual licensing.

No license-changing pull request should be merged solely on the basis of the public GitHub contributor count.