import {
  ChangeDetectionStrategy,
  Component,
  DOCUMENT,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { catchError, filter, of } from 'rxjs';

import { AuthService } from '../../core/auth/auth.service';
import { ConfigService } from '../../core/config/config.service';
import { ProjectContext } from '../../core/project/project-context';
import { ThemeService } from '../../core/theme/theme.service';
import { Icon } from '../../shared/icon/icon';
import { IconName } from '../../shared/icon/icons';
import { Toasts } from '../../shared/toast/toast';
import { CommandPalette, PaletteAction } from './command-palette';
import { ShortcutsDialog } from './shortcuts-dialog';
import { Tour, TourService } from './tour';

const COLLAPSED_KEY = 'offshoot-sidebar';

interface NavItem {
  label: string;
  icon: IconName;
  link: unknown[];
}

const PROJECT_SCREENS: { key: string; label: string; icon: IconName }[] = [
  { key: 'overview', label: 'Overview', icon: 'layout-dashboard' },
  { key: 'inventory', label: 'Inventory', icon: 'boxes' },
  { key: 'rules', label: 'Rules', icon: 'scroll-text' },
  { key: 'plan', label: 'Plan', icon: 'map' },
  { key: 'modules', label: 'Modules', icon: 'blocks' },
  { key: 'report', label: 'Report', icon: 'file-text' },
];

const SCREEN_LABEL: Record<string, string> = {
  overview: 'Overview',
  inventory: 'Inventory',
  sources: 'Sources',
  rules: 'Rules',
  plan: 'Plan',
  modules: 'Modules',
  report: 'Report',
};

/** "G then a letter" go-to shortcuts. */
const GO_KEYS: Record<string, string> = {
  o: 'overview',
  i: 'inventory',
  r: 'rules',
  l: 'plan',
  m: 'modules',
};

function typing(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) {
    return false;
  }
  return (
    element.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) ||
    !!element.closest?.('dialog[open]')
  );
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

/** The app's frame: sidebar, top bar, breadcrumbs, palette, shortcuts, toasts and the tour. */
@Component({
  selector: 'app-shell',
  imports: [CommandPalette, Icon, RouterLink, RouterLinkActive, RouterOutlet, ShortcutsDialog, Toasts, Tour],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
  host: {
    '(document:keydown)': 'onKey($event)',
  },
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Shell implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly configService = inject(ConfigService);
  private readonly router = inject(Router);
  private readonly themeService = inject(ThemeService);
  private readonly document = inject(DOCUMENT);
  private readonly tourService = inject(TourService);
  protected readonly context = inject(ProjectContext);

  private readonly config = toSignal(this.configService.load().pipe(catchError(() => of(null))));
  private pendingGo = false;

  protected readonly user = this.auth.user;
  protected readonly theme = this.themeService.theme;
  protected readonly isSigningOut = signal(false);
  protected readonly collapsed = signal(this.readCollapsed());
  protected readonly drawerOpen = signal(false);
  protected readonly userMenuOpen = signal(false);
  protected readonly switcherOpen = signal(false);
  protected readonly paletteOpen = signal(false);
  protected readonly shortcutsOpen = signal(false);
  protected readonly isMac = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform ?? '');

  protected readonly demoMode = computed(() => this.config()?.demo_mode ?? false);
  protected readonly executionOff = computed(() => this.config()?.execution_enabled === false);
  protected readonly resetHours = computed(() => this.config()?.demo_reset_hours ?? 0);
  protected readonly canReadAudit = computed(() => {
    const role = this.user()?.role;
    return role === 'ARCHITECT' || role === 'ADMIN';
  });
  protected readonly themeToggleLabel = computed(() =>
    this.theme() === 'dark' ? 'Use light theme' : 'Use dark theme',
  );
  protected readonly userInitials = computed(() => initials(this.user()?.display_name ?? '?'));

  protected readonly projectNav = computed<NavItem[]>(() => {
    const id = this.context.projectId();
    return id
      ? PROJECT_SCREENS.map((screen) => ({
          label: screen.label,
          icon: screen.icon,
          link: ['/app/projects', id, screen.key],
        }))
      : [];
  });

  protected readonly crumbs = computed(() => {
    const location = this.context.location();
    const crumbs: { label: string; link: unknown[] | null }[] = [
      { label: 'Projects', link: ['/app/projects'] },
    ];
    if (location.screen === 'audit') {
      return [{ label: 'Audit log', link: null }];
    }
    if (location.projectId) {
      const name = this.context.project()?.name ?? 'Project';
      crumbs.push({ label: name, link: ['/app/projects', location.projectId, 'overview'] });
      if (location.screen) {
        const parentLink =
          location.screen === 'sources'
            ? ['/app/projects', location.projectId, 'inventory']
            : ['/app/projects', location.projectId, location.screen];
        crumbs.push({
          label: location.screen === 'sources' ? 'Inventory' : SCREEN_LABEL[location.screen] ?? '',
          link: location.itemId ? parentLink : null,
        });
      }
      if (location.itemId) {
        const item =
          location.screen === 'modules' ? this.context.moduleName() : this.context.sourceName();
        crumbs.push({ label: item ?? '…', link: null });
      }
    }
    crumbs[crumbs.length - 1].link = null;
    return crumbs;
  });

  constructor() {
    // Load the names the breadcrumbs and switcher need for whatever is open.
    effect(() => {
      const location = this.context.location();
      void this.context.loadProjects();
      if (location.projectId && location.screen === 'modules' && location.itemId) {
        void this.context.loadModules(location.projectId);
      }
      if (location.projectId && location.screen === 'sources' && location.itemId) {
        void this.context.loadSources(location.projectId);
      }
    });
    this.router.events.pipe(filter((event) => event instanceof NavigationEnd)).subscribe(() => {
      this.drawerOpen.set(false);
      this.userMenuOpen.set(false);
      this.switcherOpen.set(false);
    });
    // Offer the tour once, on the first visit to the public demo.
    effect(() => {
      if (this.demoMode() && !this.tourService.done() && this.tourService.step() === null) {
        this.tourService.start();
      }
    });
  }

  ngOnInit(): void {
    void this.context.loadProjects();
  }

  protected toggleTheme(): void {
    this.themeService.toggle();
  }

  protected toggleCollapsed(): void {
    this.collapsed.update((value) => !value);
    try {
      this.document.defaultView?.localStorage.setItem(COLLAPSED_KEY, this.collapsed() ? '1' : '0');
    } catch {
      // Storage blocked: the choice holds for this page.
    }
  }

  protected openPalette(): void {
    this.drawerOpen.set(false);
    this.paletteOpen.set(true);
  }

  protected onPaletteAction(action: PaletteAction): void {
    switch (action) {
      case 'theme':
        this.toggleTheme();
        break;
      case 'shortcuts':
        this.shortcutsOpen.set(true);
        break;
      case 'tour':
        this.tourService.start();
        break;
      case 'website':
        void this.router.navigateByUrl('/');
        break;
      case 'sign-out':
        this.signOut();
        break;
    }
  }

  protected startTour(): void {
    this.userMenuOpen.set(false);
    this.tourService.start();
  }

  protected showShortcuts(): void {
    this.userMenuOpen.set(false);
    this.shortcutsOpen.set(true);
  }

  protected onKey(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this.paletteOpen.update((open) => !open);
      return;
    }
    if (event.key === 'Escape') {
      this.userMenuOpen.set(false);
      this.switcherOpen.set(false);
      this.drawerOpen.set(false);
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey || typing(event.target)) {
      return;
    }
    const key = event.key.toLowerCase();
    if (this.pendingGo) {
      this.pendingGo = false;
      const projectId = this.context.workingProjectId();
      if (key === 'p') {
        void this.router.navigate(['/app/projects']);
      } else if (key === 'a' && this.canReadAudit()) {
        void this.router.navigate(['/app/admin/audit']);
      } else if (GO_KEYS[key] && projectId) {
        void this.router.navigate(['/app/projects', projectId, GO_KEYS[key]]);
      }
      return;
    }
    if (key === 'g') {
      this.pendingGo = true;
      setTimeout(() => (this.pendingGo = false), 1200);
    } else if (event.key === '?') {
      this.shortcutsOpen.set(true);
    } else if (key === 't') {
      this.toggleTheme();
    } else if (event.key === '[') {
      this.toggleCollapsed();
    }
  }

  protected signOut(): void {
    this.isSigningOut.set(true);
    this.userMenuOpen.set(false);
    // The local session ends either way, so the outcome of the request doesn't change where we go.
    const toLogin = () => void this.router.navigate(['/app/login']);
    this.auth.logout().subscribe({ next: toLogin, error: toLogin });
  }

  private readCollapsed(): boolean {
    try {
      return this.document.defaultView?.localStorage.getItem(COLLAPSED_KEY) === '1';
    } catch {
      return false;
    }
  }
}
