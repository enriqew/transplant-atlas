# Bundled CA intermediates

This directory holds intermediate CA certificates that some upstream sources rely on
but fail to send during their TLS handshake. We bundle them here so the ingest scripts
can construct a complete trust chain without disabling certificate verification.

## `fnmt_accomp.pem` — FNMT-RCM "AC Componentes Informáticos"

Used by `ingest/godt_world.py`. The GODT site (`www.transplant-observatory.org`,
served by Spain's ONT) presents a cert issued by this FNMT-RCM intermediate but
doesn't include the intermediate in the handshake, so Python/requests can't trace
the chain to the root that *is* in Mozilla/certifi.

| Property | Value |
|---|---|
| Subject | `C=ES, O=FNMT-RCM, OU=AC Componentes Informáticos` |
| Issuer | `C=ES, O=FNMT-RCM, OU=AC RAIZ FNMT-RCM` (Mozilla-trusted root) |
| SHA-256 fingerprint | `F0:38:42:1F:07:F2:0D:63:A2:0D:36:91:E5:A1:78:AB:84:59:EB:E5:70:C1:64:7B:76:90:55:4E:F2:38:76:AB` |
| Origin | Downloaded from FNMT's published location; provided by the repo owner and verified by fingerprint before commit |

Anyone updating this file MUST verify the fingerprint matches above. The
fingerprint is the *only* thing that authenticates this certificate; any cert
whose fingerprint doesn't match this value is not the FNMT intermediate and must
not be trusted.

To verify locally:

```bash
openssl x509 -in ingest/certs/fnmt_accomp.pem -noout -fingerprint -sha256 -subject -issuer
```
