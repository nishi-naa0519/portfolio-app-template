// Must match the limits in backend/app/models/contact.py.
export const CONTACT_FIELD_MAX_LENGTH = {
  name: 100,
  email: 254,
  message: 5000,
} as const

export type ContactRequest = {
  name: string
  email: string
  message: string
  // Honeypot: must stay empty for real users.
  website: string
}

export type ContactResult = 'accepted' | 'invalid' | 'rate_limited' | 'unavailable'

export async function submitContact(
  request: ContactRequest,
  signal?: AbortSignal,
): Promise<ContactResult> {
  const response = await fetch('/api/contact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (response.ok) {
    return 'accepted'
  }
  if (response.status === 422) {
    return 'invalid'
  }
  if (response.status === 429) {
    return 'rate_limited'
  }
  return 'unavailable'
}
