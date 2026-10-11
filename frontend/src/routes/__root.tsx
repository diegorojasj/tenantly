import { HeadContent, Outlet, createRootRouteWithContext } from '@tanstack/solid-router';

import { t } from '../lib/i18n';
import type { RouterContext } from '../router';

// The root route: renders the matched routes' head tags and nothing else —
// the gateway (/) and the workspace shell (/t/$org) own their own chrome.
export const Route = createRootRouteWithContext<RouterContext>()({
  head: () => ({ meta: [{ title: 'Tenantly' }] }),
  component: () => (
    <>
      <HeadContent />
      <Outlet />
    </>
  ),
  notFoundComponent: () => (
    <main class="gateway">
      <div class="gateway-card narrow">
        <p class="eyebrow">404</p>
        <h1>{t('gateway.notFoundTitle')}</h1>
        <p class="lede">{t('gateway.notFoundLede')}</p>
        <a class="btn" href="/">
          {t('gateway.backToWorkspaces')}
        </a>
      </div>
    </main>
  ),
});
