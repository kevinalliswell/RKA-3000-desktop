# Vendored protocol drivers

These are pinned, trimmed copies of upstream protocol libraries. Do not edit them
in place — re-sync from upstream and re-apply trimming instead.

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
