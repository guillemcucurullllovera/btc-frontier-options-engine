# Frontier Anonymisation Scan Disposition

The frontier pre-check reported six BTC-wallet-pattern findings.

Manual JSON inspection established that these are three unique 32-character
Massive API `request_id` values duplicated between generated `results/` and
`exports/` cache trees.

They are not Bitcoin wallet addresses, credentials, authentication tokens or
counterparty identifiers.

Both generated directories are excluded from Git and will not be included in
the frontier checkpoint.

The scanner finding is therefore classified as a documented false positive.
No cached data was altered.
