// The booking lifecycle. Which moves exist is template data (`Template.transitions`,
// served by identity and enforced by operations); this file only words them.
import { t } from './i18n';
import type { BookingStatus, Template } from './types';

/** The moves the server will accept for a booking in `status`. */
export const nextStatuses = (template: Pick<Template, 'transitions'>, status: BookingStatus): Array<BookingStatus> =>
  template.transitions[status] ?? [];

/** Verb shown on the button that moves a booking into `status`. */
export const actionVerb = (status: BookingStatus) => t(`common.verb_${status}`);

/** Moves that can't be undone get a second, explicit press (docs/USAGE.md §3.3). */
export const needsConfirm = (status: BookingStatus) => status === 'cancelled' || status === 'no_show';

export const confirmText = (status: 'cancelled' | 'no_show') => t(`common.confirm_${status}`);

/** The confirmation shown after a move, in the tenant's words. */
export const movedMessage = (who: string, labels: Record<BookingStatus, string>, status: BookingStatus) =>
  status === 'cancelled'
    ? t('common.movedCancelled', { who })
    : status === 'no_show'
      ? t('common.movedNoShow', { who, label: labels.no_show.toLowerCase() })
      : `${who}: ${labels[status].toLowerCase()}`;
