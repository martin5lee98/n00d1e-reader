# Extra certificates for the scrapers

Every `*.pem` file in this folder is added to the list of certificates the
scrapers trust, on top of the normal built-in list (see `ssl_context()` in
`scrapers/http_clients.py`).

## letsencrypt-root-yr-by-x1.pem / letsencrypt-root-ye-by-x2.pem

Let's Encrypt's "Generation Y" roots (ISRG Root YR / Root YE, created
2025-09) are not in operating systems' or Python's trusted lists yet. They
are meant to be reached through these cross-signed "bridge" certificates,
which chain up to the long-trusted ISRG Root X1 / X2. Some servers
(latepost.com, 2026-10) don't send the bridge, so verification fails with
"unable to get local issuer certificate" unless we supply it here.

Downloaded from Let's Encrypt's official page, https://letsencrypt.org/certificates/ :

    curl -o scrapers/certs/letsencrypt-root-yr-by-x1.pem https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem
    curl -o scrapers/certs/letsencrypt-root-ye-by-x2.pem https://letsencrypt.org/certs/gen-y/root-ye-by-x2.pem

These are public certificates (not secrets) and must be committed, since
GitHub Actions needs them too. They can be deleted once Root YR / YE are
included in the standard trusted lists.
