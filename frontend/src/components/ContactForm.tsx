import { useState, type ChangeEvent, type FormEvent } from 'react'
import { CONTACT_FIELD_MAX_LENGTH, submitContact, type ContactRequest } from '../api/contact'

type FormStatus = 'idle' | 'sending' | 'sent' | 'invalid' | 'rate_limited' | 'error'

const EMPTY_FORM: ContactRequest = { name: '', email: '', message: '', website: '' }

const STATUS_MESSAGES: Partial<Record<FormStatus, string>> = {
  sent: 'Thank you. Your message has been sent.',
  invalid: 'Please check your input and try again.',
  rate_limited: 'Too many messages have been sent. Please try again later.',
  error: 'Your message could not be sent. Please try again later.',
}

function ContactForm() {
  const [form, setForm] = useState<ContactRequest>(EMPTY_FORM)
  const [status, setStatus] = useState<FormStatus>('idle')

  const handleChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setStatus('sending')
    try {
      const result = await submitContact(form)
      if (result === 'accepted') {
        setForm(EMPTY_FORM)
        setStatus('sent')
      } else {
        setStatus(result === 'unavailable' ? 'error' : result)
      }
    } catch {
      setStatus('error')
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <p>
        <label htmlFor="contact-name">Name</label>
        <br />
        <input
          id="contact-name"
          name="name"
          autoComplete="name"
          required
          maxLength={CONTACT_FIELD_MAX_LENGTH.name}
          value={form.name}
          onChange={handleChange}
        />
      </p>
      <p>
        <label htmlFor="contact-email">Email</label>
        <br />
        <input
          id="contact-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          maxLength={CONTACT_FIELD_MAX_LENGTH.email}
          value={form.email}
          onChange={handleChange}
        />
      </p>
      <p>
        <label htmlFor="contact-message">Message</label>
        <br />
        <textarea
          id="contact-message"
          name="message"
          required
          rows={6}
          maxLength={CONTACT_FIELD_MAX_LENGTH.message}
          value={form.message}
          onChange={handleChange}
        />
      </p>
      {/* Honeypot: hidden from people and assistive technology; bots tend to fill it. */}
      <div className="honeypot" aria-hidden="true">
        <label htmlFor="contact-website">Website</label>
        <input
          id="contact-website"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={form.website}
          onChange={handleChange}
        />
      </div>
      <button type="submit" disabled={status === 'sending'}>
        {status === 'sending' ? 'Sending...' : 'Send'}
      </button>
      <p role="status">{STATUS_MESSAGES[status] ?? ''}</p>
    </form>
  )
}

export default ContactForm
