import type { ParentProps } from 'solid-js';
import { HydrationScript } from '@solidjs/web';

import { locale } from './lib/i18n';

// The document shell (the index.html replacement), picked up by the
// src/Document.* convention; it must render the full <html> and ships no
// client JS. No inline dehydration script is needed: QueryClientProvider
// streams its entries through Solid's hydration serializer.
export default function Document(props: ParentProps) {
  return (
    <html lang={locale()}>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="color-scheme" content="light dark" />
        <meta name="description" content="Tenantly — one console for every organization, region and location." />
        <link rel="icon" href="/favicon.ico" />
        <title>Tenantly</title>
        <HydrationScript />
      </head>
      <body>{props.children}</body>
    </html>
  );
}
