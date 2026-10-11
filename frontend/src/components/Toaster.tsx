import { For } from 'solid-js';

import { t as tr } from '../lib/i18n';
import { dismiss, toasts } from '../lib/toast';
import Icon from './Icon';

/** Bottom-of-screen confirmations; announced to screen readers as they appear. */
export default function Toaster() {
  return (
    <div class="toaster" role="status" aria-live="polite">
      <For each={toasts()}>
        {(t) => (
          <div class={['toast', t.tone]}>
            <Icon name={t.tone === 'ok' ? 'check' : 'alert'} size={16} />
            <span>{t.message}</span>
            <button type="button" class="icon-btn" aria-label={tr('common.dismiss')} onClick={() => dismiss(t.id)}>
              <Icon name="x" size={14} />
            </button>
          </div>
        )}
      </For>
    </div>
  );
}
