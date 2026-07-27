# Electrical benchmark corpus

Fixture pairs are versioned JSON: `design.json` is a small, reviewable design-spec input and `expected-findings.json` is its oracle. The oracle schema is `fixture.schema.json` (`circuit-weaver-electrical-benchmark/v1`).

Each oracle names its polarity, authoring source, provenance, stable `CW-<DOMAIN>-<NNN>` rule IDs, and rationale. `detected` means a current validator check is expected to report the condition; `unsupported` preserves a known review case without claiming current detection. Positive fixtures use `expected_absent_rule_ids` rather than an invented success finding.

`generator_authored` fixtures are intentionally simple product-shaped inputs. `independent_reference` fixtures are hand-authored adverse cases, kept separate so future benchmark metrics can report the two populations independently.

Run the corpus and enforce the checked-in precision/recall baseline with:

```console
python benchmarks/run.py --check-baseline --output .test-tmp/electrical-benchmark.json
```

The checked-in scorecard inventories every emitted validator finding rule plus the
T245/T246/T247 contract rules. Rules without a complete labelled executable
population are explicitly `unsupported` rather than receiving artificial pass
credit. The release baseline gates supported aggregate precision at 0.95 and
recall at 0.90.
