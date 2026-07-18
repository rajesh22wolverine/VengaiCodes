/** Mirrors backend mask_email() */
export function maskEmail(email: string): string {
  const [local, domain] = email.split("@");
  if (!domain) return email;
  const masked = local.length <= 2 ? local[0] + "*" : local.slice(0, 2) + "*".repeat(local.length - 2);
  return `${masked}@${domain}`;
}
