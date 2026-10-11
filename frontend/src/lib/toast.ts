// "Every action answers" (docs/USAGE.md §4): a short confirmation after each
// change. A module-scope signal is the app-wide store; it is only written
// from client event handlers, so the server render never sees a toast.
import { createSignal } from 'solid-js';

export interface Toast {
  id: number;
  message: string;
  tone: 'ok' | 'info';
}

const [toasts, setToasts] = createSignal<Array<Toast>>([], { name: 'toasts' });
let seq = 0;

export { toasts };

export function notify(message: string, tone: Toast['tone'] = 'ok') {
  const id = ++seq;
  setToasts((list) => [...list.slice(-2), { id, message, tone }]);
  setTimeout(() => dismiss(id), 3500);
}

export function dismiss(id: number) {
  setToasts((list) => list.filter((t) => t.id !== id));
}
