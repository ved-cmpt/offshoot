import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';

import { describeError } from './api-error';

describe('describeError', () => {
  it('uses the message from the API error envelope', () => {
    const error = new HttpErrorResponse({
      status: 429,
      error: { error: { code: 'RATE_LIMITED', message: 'Too many attempts.', request_id: 'x' } },
    });
    expect(describeError(error)).toBe('Too many attempts.');
  });

  it('explains when the server cannot be reached', () => {
    expect(describeError(new HttpErrorResponse({ status: 0 }))).toContain('cannot be reached');
  });

  it('does not show bodies that are not our envelope', () => {
    const error = new HttpErrorResponse({ status: 502, error: '<html>Bad Gateway</html>' });
    expect(describeError(error)).toBe('Something went wrong. Please try again.');
  });

  it('handles errors that are not HTTP errors', () => {
    expect(describeError(new Error('secret internals'))).toBe(
      'Something went wrong. Please try again.',
    );
  });
});
