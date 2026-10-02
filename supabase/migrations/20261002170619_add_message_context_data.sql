alter table public.archeon_messages
  add column if not exists context_data jsonb not null default '{}'::jsonb;

alter table public.archeon_messages
  drop constraint if exists archeon_messages_context_data_object;

alter table public.archeon_messages
  add constraint archeon_messages_context_data_object
  check (jsonb_typeof(context_data) = 'object');

comment on column public.archeon_messages.context_data is
  'Bounded structured entities and interpretation metadata; never a duplicate transcript.';
