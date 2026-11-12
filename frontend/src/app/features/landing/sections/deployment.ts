import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';

import { Icon } from '../../../shared/icon/icon';
import { Reveal } from '../../../shared/reveal';

type Mode = 'legacy' | 'shadow' | 'modern';
const MODES: Mode[] = ['legacy', 'shadow', 'modern'];

/**
 * The reference deployment model: how Offshoot fits inside an organization. A picture of the
 * model, not of a customer: the legend says what v1 builds today and what it does not.
 */
@Component({
  selector: 'app-landing-deployment',
  imports: [Icon, Reveal],
  templateUrl: './deployment.html',
  styleUrl: './deployment.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingDeployment implements OnInit {
  private readonly destroyRef = inject(DestroyRef);

  /** The facade's mode for the example module, stepping legacy, shadow, modern. */
  protected readonly mode = signal<Mode>('shadow');
  protected readonly paused = signal(false);

  ngOnInit(): void {
    const still =
      globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (still) {
      this.paused.set(true);
      return;
    }
    const timer = setInterval(() => {
      if (!this.paused()) {
        this.mode.update((mode) => MODES[(MODES.indexOf(mode) + 1) % MODES.length]);
      }
    }, 2600);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected choose(mode: Mode): void {
    this.mode.set(mode);
    this.paused.set(true);
  }
}
