# Changelog

## 0.1.1

- Ship `py.typed`, so type checkers use the package's annotations.
- Leave the labeling web app out of the wheel. It could not run from an
  installed wheel (its JS assets and migrations are not packaged); run it from a
  checkout or the `Dockerfile.web` container. The offline `croatian-stemmer-labels`
  command is unchanged.
- `croatian_stemmer.__version__` now comes from the installed package metadata.
- README: how the rules were tuned and the full repository layout.
- The sdist now carries `docs/labeling.md` and no longer carries `tests/web`,
  `docs/research.md` or `.gitignore`.

## 0.1.0

First release. A rule-based Croatian stemmer extending the Ljubešić–Pandžić
v0.1 rules with verb, participle, jotation and fleeting-*a* handling, tuned on
hr500k and checked on held-out ParlaMint-HR. Ships as a Python library with a
`croatian-stemmer` command, and as the `dict_croatian_stem` PostgreSQL text
search dictionary that produces identical stems. Includes offline tools for
preparing and scoring human labels (`croatian-stemmer-labels`).
