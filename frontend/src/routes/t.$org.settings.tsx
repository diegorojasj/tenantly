import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Show } from 'solid-js';

import { PageHead, Panel } from '../components/ui';
import { fmtMoney } from '../lib/format';
import { t } from '../lib/i18n';
import { prefetch, settingsQuery, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { updateSettings } from '../lib/tenancy';
import { notify } from '../lib/toast';
import type { SsoSettings } from '../lib/types';

// Business settings (docs/PLATFORM.md gaps 9-10): the currency and tax every
// amount and invoice uses, white-label branding, and single sign-on — stored
// now, connected later. Owners only (tenant.manage); identity validates.
export const Route = createFileRoute('/t/$org/settings')({
  loader: ({ context, params }) => {
    prefetch(context.queryClient, settingsQuery(params.org));
  },
  head: () => ({ meta: [{ title: t('settings.pageTitle') }] }),
  component: SettingsPage,
});

type Patch = Omit<Parameters<typeof updateSettings>[0], 'org'>;

function SettingsPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const settings = useQuery(() => settingsQuery(org()));
  const money = () => settings.data.money;
  const save = useMutation(() => ({
    mutationFn: ({ label: _label, ...patch }: Patch & { label: string }) => updateSettings({ org: org(), ...patch }),
    onSuccess: (_r, input) => notify(input.label),
  }));
  const [protocol, setProtocol] = createSignal<SsoSettings['protocol']>(() => settings.data.sso.protocol, {
    name: 'ssoProtocol',
  });
  const text = (d: FormData, key: string) => String(d.get(key) ?? '').trim();

  return (
    <div class="page">
      <PageHead
        eyebrow={ctx.data.tenant.name}
        title={t('settings.title')}
        lede={t('settings.lede')}
      />
      <Show when={save.error}>{(error) => <p role="alert" class="error banner">{error()?.message}</p>}</Show>

      <Panel title={t('settings.moneyTitle')} icon="billing">
        <form
          class="form"
          onSubmit={(event) => {
            event.preventDefault();
            const d = new FormData(event.currentTarget);
            save.mutate({
              currency: text(d, 'currency'),
              taxRate: text(d, 'taxRate') || '0',
              taxLabel: text(d, 'taxLabel'),
              pricesIncludeTax: d.get('inclusive') === 'yes',
              label: t('settings.toastMoneySaved'),
            });
          }}
        >
          <label>
            <span class="form-label">{t('settings.currency')}</span>
            <select name="currency" value={money().currency}>
              <For each={settings.data.currencies}>{(code) => <option value={code}>{code}</option>}</For>
            </select>
            <span class="muted hint">
              {t('settings.currencyHint', { example: fmtMoney('10.00', money().currency) })}
            </span>
          </label>
          <label>
            <span class="form-label">{t('settings.taxName')}</span>
            <input type="text" name="taxLabel" required maxlength="20" value={money().taxLabel} />
          </label>
          <label>
            <span class="form-label">{t('settings.taxRate')}</span>
            <input type="number" name="taxRate" min="0" max="100" step="0.01" value={money().taxRate} />
          </label>
          <label>
            <span class="form-label">{t('settings.prices')}</span>
            <select name="inclusive" value={money().pricesIncludeTax ? 'yes' : 'no'}>
              <option value="yes">{t('settings.pricesInclusive')}</option>
              <option value="no">{t('settings.pricesExclusive')}</option>
            </select>
          </label>
          <button type="submit" class="btn" disabled={save.isPending}>
            {t('settings.saveMoney')}
          </button>
        </form>
      </Panel>

      <Panel title={t('settings.brandingTitle')} icon="tag">
        <form
          class="form"
          onSubmit={(event) => {
            event.preventDefault();
            const d = new FormData(event.currentTarget);
            save.mutate({ logoUrl: text(d, 'logoUrl'), customDomain: text(d, 'customDomain'), label: t('settings.toastBrandingSaved') });
          }}
        >
          <label>
            <span class="form-label">{t('settings.logoUrl')}</span>
            <input type="url" name="logoUrl" placeholder="https://…/logo.svg" maxlength="500" value={settings.data.branding.logoUrl} />
            <span class="muted hint">{t('settings.logoHint')}</span>
          </label>
          <Show when={settings.data.branding.logoUrl}>
            {(src) => <img class="tenant-logo preview" src={src()} alt={t('settings.currentLogo')} width="48" height="48" />}
          </Show>
          <label>
            <span class="form-label">{t('settings.customDomain')}</span>
            <input type="text" name="customDomain" placeholder="book.example.com" maxlength="253" value={settings.data.branding.customDomain} />
            <span class="muted hint">{t('settings.domainHint')}</span>
          </label>
          <button type="submit" class="btn" disabled={save.isPending}>
            {t('settings.saveBranding')}
          </button>
        </form>
      </Panel>

      <Panel title={t('settings.ssoTitle')} icon="shield" aside={<span class="pill neutral">{t('settings.notConnected')}</span>}>
        <form
          class="form"
          onSubmit={(event) => {
            event.preventDefault();
            const d = new FormData(event.currentTarget);
            save.mutate({
              sso: { protocol: protocol(), issuer: text(d, 'issuer'), metadataUrl: text(d, 'metadataUrl'), clientId: text(d, 'clientId') },
              label: t('settings.toastSsoSaved'),
            });
          }}
        >
          <p class="muted">
            {t('settings.ssoIntro')}
          </p>
          <label>
            <span class="form-label">{t('settings.protocol')}</span>
            <select value={protocol()} onChange={(event) => setProtocol(event.currentTarget.value as SsoSettings['protocol'])}>
              <option value="none">{t('settings.protocolNone')}</option>
              <option value="saml">SAML 2.0</option>
              <option value="oidc">OpenID Connect</option>
            </select>
          </label>
          <Show when={protocol() === 'saml'}>
            <label>
              <span class="form-label">{t('settings.metadataUrl')}</span>
              <input type="url" name="metadataUrl" required placeholder="https://idp.example.com/metadata" value={settings.data.sso.metadataUrl} />
            </label>
          </Show>
          <Show when={protocol() === 'oidc'}>
            <label>
              <span class="form-label">{t('settings.issuer')}</span>
              <input type="url" name="issuer" required placeholder="https://login.example.com" value={settings.data.sso.issuer} />
            </label>
            <label>
              <span class="form-label">{t('settings.clientId')}</span>
              <input type="text" name="clientId" required value={settings.data.sso.clientId} />
            </label>
          </Show>
          <button type="submit" class="btn" disabled={save.isPending}>
            {t('settings.saveSso')}
          </button>
        </form>
      </Panel>
    </div>
  );
}
