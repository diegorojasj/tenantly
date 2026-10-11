import { For } from 'solid-js';

import { locale, localeNames, locales, setLocale, t } from '../lib/i18n';
import type { Locale } from '../lib/i18n';

/** English / Español. Picking one stores it in a cookie and reloads the page in that language. */
export default function LanguageSwitch() {
  return (
    <select
      class="lang-switch"
      aria-label={t('common.language')}
      title={t('common.language')}
      value={locale()}
      onChange={(e) => setLocale(e.currentTarget.value as Locale)}
    >
      <For each={locales}>{(l) => <option value={l} selected={l === locale()}>{localeNames[l]}</option>}</For>
    </select>
  );
}
