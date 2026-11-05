import { HttpErrorResponse } from '@angular/common/http';

const GENERIC_MESSAGE = 'Something went wrong. Please try again.';
const UNREACHABLE_MESSAGE = 'The server cannot be reached. Check your connection and try again.';

/** Turn any failed request into a sentence that is safe to show to the user. */
export function describeError(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) {
    return GENERIC_MESSAGE;
  }
  if (error.status === 0) {
    return UNREACHABLE_MESSAGE;
  }
  // The API's envelope is {error: {code, message, request_id}}. Its messages are
  // written for users. Anything else (for example a proxy's error page) is not.
  const envelope = error.error as { error?: { message?: unknown } } | null;
  const message = envelope?.error?.message;
  return typeof message === 'string' && message ? message : GENERIC_MESSAGE;
}
