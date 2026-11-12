import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  model,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';

import { ProjectContext } from '../../core/project/project-context';
import { Icon } from '../../shared/icon/icon';
import { IconName } from '../../shared/icon/icons';
import { MODULE_STATE_TEXT } from '../modernization/modernization.service';

export interface Command {
  id: string;
  group: 'Go to' | 'Modules' | 'Rules' | 'Sources' | 'Actions';
  title: string;
  hint?: string;
  icon: IconName;
  keywords?: string;
  run: () => void;
}

/** Subsequence match: every typed character in order. Earlier and denser matches score higher. */
export function score(query: string, text: string): number {
  const q = query.trim().toLowerCase();
  if (!q) {
    return 1;
  }
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) {
    return 1000 - at;
  }
  let position = -1;
  let gaps = 0;
  for (const char of q) {
    const next = t.indexOf(char, position + 1);
    if (next < 0) {
      return 0;
    }
    gaps += next - position - 1;
    position = next;
  }
  return Math.max(1, 500 - gaps);
}

export type PaletteAction = 'theme' | 'shortcuts' | 'tour' | 'sign-out' | 'website';

const SCREENS: { key: string; title: string; icon: IconName }[] = [
  { key: 'overview', title: 'Overview', icon: 'layout-dashboard' },
  { key: 'inventory', title: 'Inventory and call graph', icon: 'boxes' },
  { key: 'rules', title: 'Business rules', icon: 'scroll-text' },
  { key: 'plan', title: 'Plan', icon: 'map' },
  { key: 'modules', title: 'Modules', icon: 'blocks' },
  { key: 'report', title: 'Assessment report', icon: 'file-text' },
];

/**
 * Ctrl/Cmd+K: jump to any screen, module, rule or source, or run an action. A native modal
 * dialog (focus stays inside, Escape closes), with the combobox and listbox pattern inside.
 */
@Component({
  selector: 'app-command-palette',
  imports: [Icon],
  templateUrl: './command-palette.html',
  styleUrl: './command-palette.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CommandPalette {
  private readonly router = inject(Router);
  private readonly context = inject(ProjectContext);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('search');

  readonly open = model(false);
  readonly canReadAudit = model(false);
  readonly action = output<PaletteAction>();

  protected readonly query = signal('');
  protected readonly active = signal(0);
  private readonly loaded = signal(0);

  protected readonly commands = computed<Command[]>(() => {
    this.loaded();
    const projectId = this.context.workingProjectId();
    const list: Command[] = [];
    const go = (commands: unknown[], extras?: Record<string, unknown>) => () =>
      void this.router.navigate(commands, extras);

    list.push({ id: 'go-projects', group: 'Go to', title: 'Projects', icon: 'folder-kanban', run: go(['/app/projects']) });
    if (projectId) {
      const name = this.context.projects()?.find((project) => project.id === projectId)?.name ?? 'project';
      for (const screen of SCREENS) {
        list.push({
          id: `go-${screen.key}`,
          group: 'Go to',
          title: screen.title,
          hint: name,
          icon: screen.icon,
          run: go(['/app/projects', projectId, screen.key]),
        });
      }
    }
    if (this.canReadAudit()) {
      list.push({ id: 'go-audit', group: 'Go to', title: 'Audit log', icon: 'history', run: go(['/app/admin/audit']) });
    }
    for (const project of this.context.projects() ?? []) {
      if (project.id !== projectId) {
        list.push({
          id: `project-${project.id}`,
          group: 'Go to',
          title: `Open ${project.name}`,
          hint: 'project',
          icon: 'folder-kanban',
          run: go(['/app/projects', project.id, 'overview']),
        });
      }
    }
    const modules = this.context.modules();
    if (projectId && modules?.projectId === projectId) {
      for (const module of modules.items) {
        list.push({
          id: `module-${module.id}`,
          group: 'Modules',
          title: module.program,
          hint: MODULE_STATE_TEXT[module.state],
          keywords: `${module.target_service ?? ''} module`,
          icon: 'blocks',
          run: go(['/app/projects', projectId, 'modules', module.id]),
        });
      }
    }
    const rules = this.context.rules();
    if (projectId && rules?.projectId === projectId) {
      for (const rule of rules.items) {
        list.push({
          id: `rule-${rule.id}`,
          group: 'Rules',
          title: rule.title,
          hint: `${rule.program} · ${rule.state.toLowerCase()}`,
          keywords: rule.program,
          icon: 'scroll-text',
          run: go(['/app/projects', projectId, 'rules'], { queryParams: { program: rule.program, rule: rule.id } }),
        });
      }
    }
    const sources = this.context.sources();
    if (projectId && sources?.projectId === projectId) {
      for (const source of sources.items) {
        list.push({
          id: `source-${source.id}`,
          group: 'Sources',
          title: source.name,
          hint: `${source.kind.toLowerCase()}, ${source.line_count} lines`,
          icon: 'file-code-2',
          run: go(['/app/projects', projectId, 'sources', source.id]),
        });
      }
    }
    const act = (action: PaletteAction) => () => this.action.emit(action);
    list.push(
      { id: 'act-theme', group: 'Actions', title: 'Switch theme', icon: 'sun', keywords: 'dark light', run: act('theme') },
      { id: 'act-shortcuts', group: 'Actions', title: 'Keyboard shortcuts', icon: 'keyboard', keywords: 'help', run: act('shortcuts') },
      { id: 'act-tour', group: 'Actions', title: 'Take the guided tour', icon: 'compass', keywords: 'demo walkthrough', run: act('tour') },
      { id: 'act-website', group: 'Actions', title: 'Open the Offshoot website', icon: 'external-link', keywords: 'landing home', run: act('website') },
      { id: 'act-sign-out', group: 'Actions', title: 'Sign out', icon: 'log-out', keywords: 'logout', run: act('sign-out') },
    );
    return list;
  });

  protected readonly results = computed(() => {
    const query = this.query();
    return this.commands()
      .map((command) => ({ command, score: score(query, `${command.title} ${command.hint ?? ''} ${command.keywords ?? ''}`) }))
      .filter((entry) => entry.score > 0)
      .sort((a, b) => (query ? b.score - a.score : 0))
      .slice(0, 60)
      .map((entry) => entry.command);
  });

  protected readonly groups = computed(() => {
    const groups: { name: string; items: { command: Command; index: number }[] }[] = [];
    this.results().forEach((command, index) => {
      let group = groups.find((item) => item.name === command.group);
      if (!group) {
        group = { name: command.group, items: [] };
        groups.push(group);
      }
      group.items.push({ command, index });
    });
    return groups;
  });

  constructor() {
    effect(() => {
      const dialog = this.dialog().nativeElement;
      if (this.open() && !dialog.open) {
        this.query.set('');
        this.active.set(0);
        dialog.showModal?.();
        queueMicrotask(() => this.input().nativeElement.focus());
        void this.preload();
      } else if (!this.open() && dialog.open) {
        dialog.close();
      }
    });
  }

  private async preload(): Promise<void> {
    await this.context.loadProjects();
    const projectId = this.context.workingProjectId();
    if (projectId) {
      await Promise.all([
        this.context.loadModules(projectId),
        this.context.loadRules(projectId),
        this.context.loadSources(projectId),
      ]);
    }
    this.loaded.update((n) => n + 1);
  }

  protected type(value: string): void {
    this.query.set(value);
    this.active.set(0);
  }

  protected onKey(event: KeyboardEvent): void {
    const count = this.results().length;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (count) {
        const step = event.key === 'ArrowDown' ? 1 : -1;
        this.active.set((this.active() + step + count) % count);
        this.scrollActive();
      }
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const command = this.results()[this.active()];
      if (command) {
        this.choose(command);
      }
    }
  }

  protected choose(command: Command): void {
    this.open.set(false);
    command.run();
  }

  protected closed(): void {
    // Escape, or the dialog closed itself.
    this.open.set(false);
  }

  protected backdrop(event: MouseEvent): void {
    if (event.target === this.dialog().nativeElement) {
      this.open.set(false);
    }
  }

  private scrollActive(): void {
    queueMicrotask(() =>
      this.dialog()
        .nativeElement.querySelector(`#palette-option-${this.active()}`)
        ?.scrollIntoView?.({ block: 'nearest' }),
    );
  }
}
