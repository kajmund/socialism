-- Schema for the lagen.nu cache. Applied in the same Supabase project as
-- Socialism, isolated from prompt_fields / prompt_overrides.
--
-- Poller/fetcher use the service-role key. RLS is intentionally off in v1
-- (internal background job, no direct client access).

create schema if not exists lagen_nu;

create table if not exists lagen_nu.documents (
  url text primary key,
  doc_type text not null,        -- sfs/dv/forarbete/myndfs/myndprax/keyword
  sfs_nr text,
  feed_source text,
  atom_updated timestamptz,
  content_hash text,
  fetched_at timestamptz default now(),
  format text,                    -- json/rdf/html
  raw_content text
);

create table if not exists lagen_nu.document_versions (
  id bigint generated always as identity primary key,
  sfs_nr text not null,
  amending_sfs text not null,
  konsolidering_url text,
  content_hash text,
  raw_content text,
  is_current boolean default false,
  fetched_at timestamptz default now(),
  unique (sfs_nr, amending_sfs)
);

create table if not exists lagen_nu.feed_state (
  feed_url text primary key,
  last_polled_at timestamptz,
  last_seen_entry_updated timestamptz
);

-- Fas 1 queue. Missing from the original Fas 2 DDL; fetcher drains this.
create table if not exists lagen_nu.pending_fetch (
  url text primary key,
  atom_id text not null,
  feed_url text not null,
  doc_type text not null,
  atom_updated timestamptz not null,
  title text,
  enqueued_at timestamptz default now()
);

create table if not exists lagen_nu.paragraphs (
  url text not null references lagen_nu.documents (url) on delete cascade,
  anchor text not null,
  label text,
  text text not null,
  search_vector tsvector generated always as (
    to_tsvector('swedish', coalesce(text, ''))
  ) stored,
  primary key (url, anchor)
);

create index if not exists idx_documents_doc_type
  on lagen_nu.documents (doc_type);

create index if not exists idx_document_versions_sfs
  on lagen_nu.document_versions (sfs_nr, is_current);

create index if not exists idx_pending_fetch_enqueued
  on lagen_nu.pending_fetch (enqueued_at);

create index if not exists idx_paragraphs_search
  on lagen_nu.paragraphs using gin (search_vector);

-- Fas 3: Swedish full-text index over cached document text.
alter table lagen_nu.documents
  add column if not exists search_vector tsvector
  generated always as (to_tsvector('swedish', coalesce(raw_content, ''))) stored;

create index if not exists idx_documents_search
  on lagen_nu.documents using gin (search_vector);
