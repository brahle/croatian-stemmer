# Security policy

Please report vulnerabilities privately through a GitHub security advisory:
open the repository's **Security** tab and choose **Report a vulnerability**.
Do not open a public issue for a security problem.

In scope:

- the Python stemmer (`croatian_stemmer`) and its command-line tools;
- the PostgreSQL extension in `pg/` (`dict_croatian_stem`);
- the labeling web app in `src/croatian_stemmer/labeling/web`.

The labeling app is self-hosted. Whoever deploys it owns its configuration,
including the identity provider, database credentials, TLS and network
exposure; see [docs/labeling-web.md](docs/labeling-web.md). Reports about the
app's code and defaults are welcome; problems that come only from a particular
deployment's configuration are for that deployment's operator.
