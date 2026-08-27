# Curated preference training and evaluation

Variant selection freezes the winning and rejected critic features, display ranks, presentation
order, reviewer, brand, category, and brief fingerprint. A raw selection remains audit feedback
and is excluded from training until an authorized reviewer marks it curated with a dataset version.

Curated feedback expands into one explicit pairwise row for every winner/rejected pair. Import and
export validate tenant ownership, campaign feedback identity, feature schema, dataset version, and
duplicate comparison IDs.

## Leakage prevention

The default split groups duplicate brief fingerprints, which also keeps every campaign together.
`brand_held_out_split` reserves complete brands for generalization evaluation. Split validation
raises if a campaign or brief fingerprint appears in more than one partition.

## Model artifacts

The Bradley–Terry artifact includes:

- The exact critic-feature schema.
- Versioned weights and model identity.
- Dataset and split fingerprints.
- Training sample count and hyperparameters.
- Training timestamp and artifact schema version.

Loading rejects unknown schemas, changed features, non-finite weights, and invalid metadata. The
runtime loads an artifact only when `PREFERENCE_MODEL_PATH` is configured. Raw feedback never
changes production weights automatically.

~~~bash
make preference-train
make preference-eval
~~~

The shipped comparison file is synthetic. Its report exercises held-out pairwise accuracy,
NDCG@3, expected calibration error, top-choice selection rate, and brand/category slices. Small
slices are suppressed with warnings. Human results remain pending until reviewed comparisons are
collected.
