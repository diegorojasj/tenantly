import { render } from '@solidjs/testing-library';
import { QueryClient, QueryClientProvider } from '@tanstack/solid-query';
import { flush } from 'solid-js';
import { describe, expect, test, vi } from 'vitest';

import type { Template } from '../lib/types';

const calls = { options: 0 };
vi.mock('../lib/queries', () => ({
  bookingOptionsQuery: (org: string, location: string) => ({
    queryKey: ['booking-options', org, location],
    queryFn: async () => {
      calls.options++;
      return options;
    },
    staleTime: 0,
  }),
  availabilityQuery: (...args: Array<unknown>) => ({
    queryKey: ['availability', ...args],
    queryFn: async () => ({ slots: ['08:00', '09:00'], reason: '' }),
    staleTime: 0,
  }),
}));
vi.mock('../lib/scope', () => ({ useCurrency: () => () => 'USD' }));
vi.mock('../lib/ops', () => ({ createBooking: vi.fn(), joinSession: vi.fn(), scheduleSession: vi.fn() }));
vi.mock('@tanstack/solid-router', () => ({ Link: (p: { children: unknown }) => p.children }));

const { default: NewBooking } = await import('./NewBooking');

const offering = (over: object) => ({
  id: crypto.randomUUID(),
  kind: 'rental',
  name: 'Kayak',
  category: 'General',
  minutes: 120,
  price: '30.00',
  unit: 'hour',
  capacity: 1,
  time: 'window',
  place: 'on_site',
  subjectType: null,
  fields: {},
  active: true,
  requires: [{ pick: false, role: 'Kayak', type: 'asset', quantity: 1 }],
  ...over,
});
const resource = (role: string, type: string, i: number) => ({
  id: `${role}-${i}`,
  locationId: 'dock',
  type,
  name: `${role} ${i}`,
  role,
  attributes: {},
  parentId: null,
  status: 'available',
});
const options = {
  locationId: 'dock',
  tz: 'UTC',
  hours: [480, 1200],
  approval: false,
  offerings: [offering({ name: 'Kayak' })],
  classes: [
    offering({ kind: 'class', name: 'Tour', unit: 'session', time: 'slot', capacity: 10, requires: [{ pick: true, role: 'Guide', type: 'staff', quantity: 1 }] }),
  ],
  resources: [resource('Kayak', 'asset', 1), resource('Guide', 'staff', 1)],
  customers: [{ id: 'c1', name: 'Ana', detail: 'ana@example.com', subjects: [] }],
  sessions: [],
  subjectTypes: [],
  bookingFields: [],
};
const template = {
  open: 480,
  close: 1200,
  resourceTypes: [],
  presets: [],
  terms: { booking: 'Booking', bookings: 'Bookings', location: 'Location', customer: 'Customer', customers: 'Customers' },
} as unknown as Template;

describe('<NewBooking />', () => {
  // Regression: each form used to subscribe to the booking options again,
  // which re-created the form on every mount — a synchronous loop that froze
  // the tab until the browser ran out of memory.
  test('opens on the slot form, reading the options once', async () => {
    const { findByText } = render(() => (
      <QueryClientProvider client={new QueryClient()}>
        <NewBooking org="o" template={template} sites={[]} siteId="dock" day="2026-10-13" onClose={() => {}} />
      </QueryClientProvider>
    ));
    flush();
    expect(await findByText(/Kayak/)).toBeInTheDocument();
    expect(calls.options).toBe(1);
  });
});
