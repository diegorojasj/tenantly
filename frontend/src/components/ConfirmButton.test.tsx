import { fireEvent, render } from '@solidjs/testing-library';
import { flush } from 'solid-js';
import { describe, expect, test, vi } from 'vitest';

import { movedMessage, needsConfirm, nextStatuses } from '../lib/lifecycle';
import type { Template } from '../lib/types';
import ConfirmButton from './ConfirmButton';

describe('<ConfirmButton />', () => {
  test('the first press only arms it; the second confirms', () => {
    const onConfirm = vi.fn();
    const { getByRole } = render(() => <ConfirmButton label="Refund" confirm="Refund $20?" onConfirm={onConfirm} />);
    const button = getByRole('button');
    fireEvent.click(button);
    flush();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(button).toHaveTextContent('Refund $20?');
    fireEvent.click(button);
    flush();
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(button).toHaveTextContent('Refund');
  });

  test('disarms itself if the second press never comes', () => {
    vi.useFakeTimers();
    const onConfirm = vi.fn();
    const { getByRole } = render(() => <ConfirmButton label="Retire" confirm="Stop selling it?" onConfirm={onConfirm} />);
    const button = getByRole('button');
    fireEvent.click(button);
    flush();
    vi.advanceTimersByTime(4100);
    flush();
    expect(button).toHaveTextContent('Retire');
    fireEvent.click(button);
    flush();
    expect(onConfirm).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});

describe('lifecycle', () => {
  const labels = {
    requested: 'Requested', confirmed: 'Reserved', checked_in: 'Out',
    completed: 'Returned', no_show: 'No-show', cancelled: 'Cancelled',
  } as const;

  test('only irreversible moves ask twice', () => {
    expect(needsConfirm('cancelled')).toBe(true);
    expect(needsConfirm('no_show')).toBe(true);
    expect(needsConfirm('checked_in')).toBe(false);
  });

  test('moves come from the template, and unknown statuses have none', () => {
    const template: Pick<Template, 'transitions'> = { transitions: { confirmed: ['completed', 'cancelled'], completed: [] } };
    expect(nextStatuses(template, 'confirmed')).toEqual(['completed', 'cancelled']);
    expect(nextStatuses(template, 'completed')).toEqual([]);
    expect(nextStatuses(template, 'checked_in')).toEqual([]);
  });

  test('confirmations use the tenant’s words', () => {
    expect(movedMessage('Kayak K2', labels, 'checked_in')).toBe('Kayak K2: out');
    expect(movedMessage('Ana', labels, 'cancelled')).toContain('refunded');
  });
});
