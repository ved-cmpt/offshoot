import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

/** The public pitch site at "/". No sign-in, no API call. */
@Component({
  selector: 'app-landing',
  imports: [RouterLink],
  template: `
    <main id="main" class="landing">
      <h1>AI-assisted COBOL → C# modernization, with proof</h1>
      <a class="button" routerLink="/app">Try the live demo</a>
    </main>
  `,
  styles: `
    .landing {
      display: grid;
      gap: var(--space-5);
      justify-items: start;
      max-width: var(--page-width);
      margin: 0 auto;
      padding: var(--space-9) var(--space-4);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Landing {}
