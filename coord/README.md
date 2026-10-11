# Coordination protocol (manager-owned)

Shared directory `coord/` lives outside worker worktrees/branches. Workers use
native session messaging first; these files are the durable record.

- `tasks.json`: task ID → {role, owner_session, objective, allowed_paths,
  contract_version, state, acceptance, evidence, updated_utc}. States: assigned,
  running, blocked, review, accepted.
- `workers.json`: session → {proposed_role, status, last_heartbeat_utc, note}.
  Worker status vocabulary: running (task in progress), awaiting-go-ahead
  (acked, worker-side approval pending), idle (no active task), stalled
  (30-min rule tripped, see Liveness).
- `inbox/`: manager → worker task messages (one JSON per task ID, atomic write).
- `outbox/`: worker → manager completion messages (one JSON per task ID).
- Message schema: {id, task_id, from, to, utc, kind, body, ack_required}.
  Completion adds {commit, results, unresolved, next_dependency, repro_commands}.

Liveness: workers heartbeat via native reply + outbox status on state change.
Manager marks stalled after 30 min without heartbeat on a running task and
reconciles before reassigning. Silence is never success.

Native messaging is preferred and tested with one task/ack round trip per worker
before full dispatch. Inbox files alone do not wake an idle CLI; activation uses
verified native messaging. If native messaging becomes unavailable, manager
reports the limitation and falls back to owner-pasted bootstrap messages.
