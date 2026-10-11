import { render } from '@solidjs/testing-library';
import { describe, expect, test } from 'vitest';

import { Ring } from './Spark';
import { Boundary, RoleChip } from './ui';

describe('<Boundary />', () => {
  test('reads access refusals as a boundary, not a crash', () => {
    const { getByRole, queryByText } = render(() => (
      <Boundary error={Object.assign(new Error('You are not a member of Helix Health'), { status: 403 })} reset={() => {}} />
    ));
    expect(getByRole('alert')).toHaveTextContent('You don’t have access to this');
    expect(getByRole('alert')).toHaveTextContent('not a member of Helix Health');
    // Retrying a refusal can't succeed, so no retry is offered.
    expect(queryByText('Retry')).toBeNull();
  });

  test('offers a retry for unexpected failures', () => {
    const { getByText } = render(() => <Boundary error={new Error('boom')} reset={() => {}} />);
    expect(getByText('Something went wrong')).toBeInTheDocument();
    expect(getByText('Retry')).toBeInTheDocument();
  });
});

describe('primitives', () => {
  test('RoleChip labels and classes the role', () => {
    const { getByText } = render(() => <RoleChip role="regional_manager" />);
    expect(getByText('Area manager')).toHaveClass('chip', 'role-regional_manager');
  });

  test('Ring flags meters past 85%', () => {
    const { container } = render(() => <Ring value={92} />);
    expect(container.querySelector('.ring-fill')).toHaveClass('hot');
  });
});
