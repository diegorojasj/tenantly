// "Irreversible means two steps" (docs/USAGE.md §4): the first press arms the
// button and says what will happen; the second does it. It disarms itself
// after a few seconds so a stray click later can't fire it.
import { createSignal, onSettled } from 'solid-js';

export default function ConfirmButton(props: {
  label: string;
  confirm: string;
  onConfirm: () => void;
  disabled?: boolean;
  class?: string;
}) {
  const [armed, setArmed] = createSignal(false, { name: 'confirmArmed' });
  let timer: ReturnType<typeof setTimeout> | undefined;
  onSettled(() => () => clearTimeout(timer));
  return (
    <button
      type="button"
      class={['btn', props.class, { danger: armed() }]}
      disabled={props.disabled}
      onClick={(event) => {
        event.stopPropagation();
        if (armed()) {
          clearTimeout(timer);
          setArmed(false);
          props.onConfirm();
          return;
        }
        setArmed(true);
        timer = setTimeout(() => setArmed(false), 4000);
      }}
    >
      {armed() ? props.confirm : props.label}
    </button>
  );
}
