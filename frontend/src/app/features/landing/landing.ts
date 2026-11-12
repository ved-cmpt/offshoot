import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { ThemeService } from '../../core/theme/theme.service';
import { Icon } from '../../shared/icon/icon';
import { HeroVisual } from './hero-visual';
import { DOCS, LandingData, REPO_URL, evaluationRow } from './landing-data';
import { LandingCapabilities } from './sections/capabilities';
import { LandingDemos } from './sections/demos';
import { LandingDeployment } from './sections/deployment';
import { LandingPipeline } from './sections/pipeline';
import { LandingProblem } from './sections/problem';
import { LandingResults } from './sections/results';

export interface Stat {
  value: string;
  label: string;
  source: string;
}

/** The public pitch site at "/" (ADR-052). It never signs in or calls the API (ADR-054). */
@Component({
  selector: 'app-landing',
  imports: [
    HeroVisual,
    Icon,
    LandingCapabilities,
    LandingDemos,
    LandingDeployment,
    LandingPipeline,
    LandingProblem,
    LandingResults,
    RouterLink,
  ],
  templateUrl: './landing.html',
  styleUrl: './landing.scss',
  host: { '(document:keydown.escape)': 'closeMenu()' },
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Landing implements OnInit {
  private readonly landing = inject(LandingData);
  private readonly themeService = inject(ThemeService);

  protected readonly data = this.landing.snapshot;
  protected readonly failed = this.landing.failed;
  protected readonly menuOpen = signal(false);
  protected readonly theme = this.themeService.theme;
  protected readonly docs = DOCS;
  protected readonly repo = REPO_URL;
  protected readonly year = new Date().getUTCFullYear();

  protected readonly stats = computed<Stat[]>(() => {
    const data = this.data();
    if (!data) {
      return [];
    }
    const r = data.api.rounding;
    const afterRepair = evaluationRow(data, 'Equivalence 100% after repair');
    const approvals = evaluationRow(data, 'Model-initiated approvals');
    return [
      {
        value: String(r.cases),
        label: 'seeded cases per module, run against the real COBOL',
        source: `RATECALC run, seed ${r.seed}`,
      },
      {
        value: String(r.failed),
        label: 'one-cent differences caught before anyone could approve',
        source: 'Stored run on the public demo',
      },
      {
        value: afterRepair ? afterRepair[1].split(',')[0] : '',
        label: 'modules equivalent after repair, with one repair used',
        source: 'docs/EVALUATION.md, mock pipeline',
      },
      {
        value: approvals ? approvals[1] : '',
        label: 'approvals made by the model, mock or live',
        source: 'docs/EVALUATION.md',
      },
    ];
  });

  ngOnInit(): void {
    this.landing.load();
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }

  protected closeMenu(): void {
    this.menuOpen.set(false);
  }

  protected toggleTheme(): void {
    this.themeService.toggle();
  }
}
