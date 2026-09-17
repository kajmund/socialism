# Customer products and module entitlements

`Kund.product` and `Kund.available_modules` answer different questions:

- `product` selects the complete frontend shell. `null` uses the standard
  Socialism admin shell; `sme` uses the SME Messenger shell.
- `available_modules` controls backend capabilities, prompt catalogs and
  module entitlements. A product shell may hide the standard module navigation.

Customer products are declared in `backend/app/products/registry.py`. Unknown
product ids are rejected by the customer API. `GET /me` exposes the selected
product so the frontend can choose its route tree before rendering a shell.

The SME API lives under `/sme` and requires an authenticated user bound to a
customer whose product is `sme`. Its inbox combines existing expert library
messages with product-specific panel messages and per-user read cursors.

SME expert chat uses one product-level `/ws/sme` connection. Every send and
output event carries `thread_type`, `thread_id`, and `request_id`, allowing
several expert turns to stream concurrently while the UI routes each event to
the correct conversation. The socket remains mounted when the selected thread
changes, and expert tools use the same tool-aware service as the library chat.
