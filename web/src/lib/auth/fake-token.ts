/**
 * Dev tokens for the backend's fake verifier
 * (backend/app/providers/auth/fake.py): `fake|<subject>|<email>|<name>`.
 * Only accepted by an API running with AUTH_PROVIDER=fake (local/test).
 */

export type DevIdentity = { subject: string; email: string; name: string };

const PREFIX = "fake|";

export function makeFakeToken({ subject, email, name }: DevIdentity): string {
  for (const part of [subject, email, name]) {
    if (part.includes("|")) throw new Error("fake token fields must not contain '|'");
  }
  if (!subject) throw new Error("fake token needs a subject");
  return `${PREFIX}${subject}|${email}|${name}`;
}

/** The same email always signs in as the same person. */
export function devIdentityFor(email: string, name: string): DevIdentity {
  const normalised = email.trim().toLowerCase();
  if (!/^[^\s@|]+@[^\s@|]+\.[^\s@|]+$/.test(normalised)) {
    throw new Error("Enter a valid email address");
  }
  const cleanName = name.trim().replace(/\|/g, "");
  return {
    subject: `dev_${normalised.replace(/[^a-z0-9]/g, "_")}`,
    email: normalised,
    name: cleanName,
  };
}
