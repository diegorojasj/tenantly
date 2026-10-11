// Access refusals are answers, not failures: no retry, and a boundary that says
// "no access" instead of "something went wrong". The services word them in the
// viewer's language, so they are told apart by status (the server's ApiError
// carries it across the server-function boundary), never by their words.
const REFUSALS = new Set([401, 403, 404]);

export function isRefusal(error: unknown): boolean {
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status === 'number' && REFUSALS.has(status);
}
