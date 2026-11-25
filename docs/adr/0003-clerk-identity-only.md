# ADR-0003: Clerk for identity only; workspaces and roles in our database

- Status: Accepted
- Date: 2026-11-25
- Implements: PLAN §4.1 and §5 decision 1 (amends SPEC §4 "managed auth with
  organisations")

## Context
SPEC §4 asks for managed auth with organisations. If the auth provider's
organisations owned membership, roles, workspace ids and (from M2)
jurisdiction restrictions would live in two places, kept in sync by webhooks.
RLS needs all of them in Postgres anyway (ADR-0002). A sync gap would then be
an authorisation bug.

## Decision
- **Clerk answers only "who is this?"** The frontend signs in with Clerk. The
  API verifies the Clerk session token itself and maps `sub` to
  `users.auth_subject`. Clerk organisations are not used.
- **Workspaces, memberships and roles live only in our database**
  (owner, admin, policy_editor, agent, viewer, integrator), behind RLS.
- **Token verification** (`app/providers/auth/clerk.py`):
  - RS256 only (no algorithm downgrade); keys come from the issuer's JWKS,
    cached for an hour, and the blocking fetch runs off the event loop.
  - Checks `iss`, `exp`, `nbf`, and requires `exp`, `iat`, `iss`, `sub`.
    5 s leeway.
  - `azp` must be in `CLERK_AUTHORIZED_PARTIES`.
  - `email` and `name` come from custom session-token claims configured in
    Clerk (`{"email": "{{user.primary_email_address}}", "name":
    "{{user.full_name}}"}`).
- **First sign-in creates our user row**, with the email stored lowercased and
  unique. Email and name are refreshed from the token on every request. An
  email already used by another account → 409.
- **Adding a member is by email** and needs that person to have signed in once
  (otherwise 404). Invitations for people who haven't signed in come later.
- **Behind an interface.** `AuthVerifier` (`providers/auth/base.py`) with a
  Clerk implementation and a fake. The fake (`fake|sub|email|name` tokens)
  keeps tests offline. Settings refuse to start with `AUTH_PROVIDER=fake`
  unless `ENVIRONMENT` is `local` or `test`.

## Alternatives considered
- **Clerk organisations as the source of membership.** Rejected: two sources of
  truth and webhook sync, for no gain, since RLS needs the data locally.
- **Zitadel Cloud or WorkOS.** Both can be hosted in the EU, and WorkOS is
  stronger for enterprise SSO. Kept as the swap path. Switching means a new
  `AuthVerifier` and re-mapping `auth_subject`; nothing else changes.
- **Self-hosted (Keycloak) or our own auth.** Operating burden and security
  surface we don't need now.

## Consequences
- **Data location:** Clerk is US-hosted and processes our *operators'*
  identities (agents, admins, policy editors: email, name, sign-in events). It
  must be listed as a subprocessor. Requesters (the people raising tickets)
  never go through Clerk. Re-decide before the first EU HR customer if that's
  a blocker; that's what the swap path above is for.
- **Email trust is delegated to Clerk.** Add-member-by-email assumes the
  token's email is verified. `primary_email_address` is a verified address
  in Clerk; keep it that way when configuring the session token.
- **Revocation lag:** a revoked Clerk session stays usable until its short-lived
  token expires (Clerk's default is about a minute), plus leeway.
- **No deletion sync yet.** Deleting a user in Clerk doesn't remove our row;
  they just can't sign in. Account deletion and GDPR erasure are M6.
- **`azp` check:** an empty `CLERK_AUTHORIZED_PARTIES` currently disables it.
  It should be required whenever `AUTH_PROVIDER=clerk` outside local/test;
  tracked as an open question in PROGRESS.md.
