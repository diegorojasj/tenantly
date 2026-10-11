// One area's messages: English is the source of truth, and Spanish must
// carry exactly the same keys (a missing or extra key fails type-checking).
// A plural message is `{ one, other }` (optionally `zero`), chosen by the
// `count` param.
export type Plural = { zero?: string; one: string; other: string };
export type Message = string | Plural;

type Mirror<E> = { [K in keyof E]: E[K] extends string ? string : Plural };

export function defineMessages<const E extends Record<string, Message>>(en: E, es: Mirror<E>) {
  return { en, es: es as Record<keyof E, Message> };
}
