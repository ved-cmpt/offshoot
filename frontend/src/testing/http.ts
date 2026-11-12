import { HttpTestingController, TestRequest } from '@angular/common/http/testing';

/**
 * Wait until a request to `url` has been made, then return it. Route guards issue their
 * requests a few ticks after navigation starts, so an immediate `expectOne` would miss them.
 */
export async function nextRequest(
  http: HttpTestingController,
  url: string,
  tries = 50,
): Promise<TestRequest> {
  for (let attempt = 0; attempt < tries; attempt++) {
    const found = http.match(url);
    if (found.length) {
      return found[0];
    }
    await new Promise((resolve) => setTimeout(resolve));
  }
  throw new Error(`No request to ${url}`);
}
