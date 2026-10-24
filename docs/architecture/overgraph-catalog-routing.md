# Overgraph catalog routing and customer isolation

Status: architectural principle. No implementation change in this step.

## Principle

A customer may have one or more separate Overgraph databases (catalogs), for
example split by knowledge area. Customer isolation happens primarily by
**choosing the right catalog**, not by adding complex tenant-filtering logic
inside Overgraph.

Implications:

- every Overgraph catalog has its own owner process and catalog identity;
- the application is responsible for resolving which catalog a request uses;
- access control happens **before** a catalog is opened or used;
- Overgraph keeps the storage/search contract simple;
- a customer can have several catalogs without becoming a multi-tenant graph.

## Ownership and identity

One owner per catalog, one catalog per owner. The owner's persistent
`catalog_id` identifies the actual catalog, not a path on a particular machine.
A client must verify the catalog identity before writing.

Multiple backend workers may use the same owner. A backend must not start its
own owner per worker, and two owners must never be active for the same catalog.

## Routing boundary

```text
request + authenticated customer
        -> application authorizes and selects catalog
        -> OvergraphWriterClient / reader for that catalog_id
        -> owner (single writer)
        -> Overgraph catalog
```

The routing/authorization decision belongs to the application layer. The owner
does not need customer-aware filtering; it owns one catalog and enforces the
catalog identity.

## What this does not change

- Existing tenant/scope fields in the current graph are not removed by this
  note; they may still be used inside a shared catalog where that model is
  already in place.
- No catalog-routing implementation, registry or per-customer deployment is
  added yet. This is a constraint for the later routing work.

## Later work

When catalog routing becomes relevant, add a small application-level registry
mapping authenticated customer/domain -> catalog identity and owner socket.
Authorization must be resolved before opening or calling the owner. The owner
protocol already carries a catalog identity so a misrouted client fails closed.
