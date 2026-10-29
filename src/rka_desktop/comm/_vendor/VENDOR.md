# Vendored protocol drivers

These are pinned, trimmed copies of upstream protocol libraries. Keep all local
corrections listed below and re-assess them on each upstream sync.

## RKA-local protocol corrections

The pinned copies now carry the following small, test-backed corrections. When re-syncing,
re-apply or drop each correction explicitly after comparing upstream behavior:

- `azbil_mfc/protocol.py`: strict CPL terminator, header, checksum-field and register-word
  validation plus outbound range checks.
- `azbil_mfc/bus.py`: reject replies from another address or with the wrong register count;
  never automatically retry a write.
- `azbil_mfc/client.py`: a forced live scale refresh cannot silently fall back to stale
  cached metadata.
- `taie_temp/modbus_rtu.py`: assemble fragmented serial reads, bound byte counts, verify
  the requested register count and write echo.
- `balance_serial/protocols/{gs_cpa,longteng}.py`: accept only documented full weight
  frames; Longteng `ST` frames are marked stable.
- `balance_serial/client.py`: tare confirmation requires a stable zero reading, not merely
  an ACK or an unstable zero.

The RKA-owned adapters additionally require live MFC scale metadata and keep all real
write methods disabled during the read-only diagnostic phase.

| Package | Upstream | Commit | License | Vendored modules | Omitted |
|---------|----------|--------|---------|------------------|---------|
| `azbil_mfc` | github.com/kevinalliswell/azbil-mfc | 83ddc491 | MIT | bus, client, protocol, constants, registers, exceptions, device_catalog, (trimmed) __init__ | dashboard/, mixer, recipe, scheduler, safety |
| `taie_temp` | github.com/kevinalliswell/taie-temp-controller | ab18b921 | Apache-2.0 | controller, modbus_rtu, register_addresses, __init__ | api, polling, acquisition |
| `balance_serial` | github.com/kevinalliswell/balance-serial | 496b7b76 | (no upstream LICENSE) | client, factory, models, exceptions, protocols/{base,gs_cpa,longteng}, __init__ | device, examples |

## Licensing note

`balance-serial` has no LICENSE file upstream. It is owned by the same owner as this
repository (kevinalliswell); vendoring here is under same-owner authorization. Recommend
adding an explicit LICENSE to the upstream repo. MIT (azbil) and Apache-2.0 (taie) require
retaining their license/notice text; their original LICENSE text is reproduced in
`azbil_mfc/` and `taie_temp/` headers/`LICENSE-*` as applicable.
