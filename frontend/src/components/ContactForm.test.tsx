import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ContactForm from './ContactForm'

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Example User' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'user@example.com' } })
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

function mockFetch(response: Response | Error) {
  const fetchMock =
    response instanceof Error
      ? vi.fn().mockRejectedValue(response)
      : vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('ContactForm', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the form to the contact API and clears it on success', async () => {
    const fetchMock = mockFetch(new Response(JSON.stringify({ status: 'accepted' }), { status: 202 }))
    render(<ContactForm />)

    fillAndSubmit()

    expect(await screen.findByText('Thank you. Your message has been sent.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/contact',
      expect.objectContaining({ method: 'POST' }),
    )
    const body: unknown = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({
      name: 'Example User',
      email: 'user@example.com',
      message: 'Hello',
      website: '',
    })
    expect(screen.getByLabelText('Name')).toHaveValue('')
  })

  it.each([
    [422, 'Please check your input and try again.'],
    [429, 'Too many messages have been sent. Please try again later.'],
    [503, 'Your message could not be sent. Please try again later.'],
  ])('shows a message for HTTP %i and keeps the input', async (status, message) => {
    mockFetch(new Response(JSON.stringify({ detail: 'x' }), { status }))
    render(<ContactForm />)

    fillAndSubmit()

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Example User')
  })

  it('shows an error when the request fails', async () => {
    mockFetch(new TypeError('Failed to fetch'))
    render(<ContactForm />)

    fillAndSubmit()

    expect(
      await screen.findByText('Your message could not be sent. Please try again later.'),
    ).toBeInTheDocument()
  })

  it('applies the backend length limits', () => {
    render(<ContactForm />)

    expect(screen.getByLabelText('Name')).toHaveAttribute('maxLength', '100')
    expect(screen.getByLabelText('Email')).toHaveAttribute('maxLength', '254')
    expect(screen.getByLabelText('Message')).toHaveAttribute('maxLength', '5000')
  })

  it('hides the honeypot field from keyboard and assistive technology', () => {
    const { container } = render(<ContactForm />)

    const honeypot = container.querySelector('input[name="website"]')
    expect(honeypot).toHaveAttribute('tabIndex', '-1')
    expect(honeypot?.closest('[aria-hidden="true"]')).not.toBeNull()
    expect(screen.queryByRole('textbox', { name: 'Website' })).toBeNull()
  })
})
