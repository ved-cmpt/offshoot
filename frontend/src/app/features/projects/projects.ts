import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';
import { ConfigService } from '../../core/config/config.service';
import { Icon } from '../../shared/icon/icon';
import { EmptyState, Skeleton } from '../../shared/ui/ui';
import { Project, ProjectsService } from './projects.service';

type ListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; projects: Project[] };

const STATUS_LABELS: Record<Project['status'], string> = {
  IMPORTED: 'Imported, not analyzed yet',
  ANALYZING: 'Analyzing',
  ANALYZED: 'Analyzed',
  FAILED: 'Analysis failed',
};

const STATUS_TONE: Record<Project['status'], string> = {
  IMPORTED: '',
  ANALYZING: 'badge--warn',
  ANALYZED: 'badge--ok',
  FAILED: 'badge--danger',
};

const SOURCE_LABELS: Record<Project['source_kind'], string> = {
  BUNDLED: 'Bundled sample',
  UPLOAD: 'Uploaded',
};

@Component({
  selector: 'app-projects',
  imports: [DatePipe, DecimalPipe, EmptyState, Icon, RouterLink, Skeleton],
  templateUrl: './projects.html',
  styleUrl: './projects.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Projects implements OnInit {
  private readonly projectsService = inject(ProjectsService);
  private readonly auth = inject(AuthService);
  private readonly config = toSignal(
    inject(ConfigService)
      .load()
      .pipe(catchError(() => of(null))),
  );

  protected readonly state = signal<ListState>({ kind: 'loading' });
  protected readonly canCreate = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ENGINEER' || role === 'ARCHITECT';
  });
  protected readonly demoMode = computed(() => this.config()?.demo_mode ?? true);
  protected readonly name = signal('');
  protected readonly archive = signal<File | null>(null);
  protected readonly uploading = signal(false);
  protected readonly uploadError = signal<string | null>(null);
  protected readonly created = signal<Project | null>(null);
  protected readonly statusLabels = STATUS_LABELS;
  protected readonly statusTone = STATUS_TONE;
  protected readonly showUpload = signal(false);
  protected readonly sourceLabels = SOURCE_LABELS;

  ngOnInit(): void {
    this.load();
  }

  protected pick(event: Event): void {
    const files = (event.target as HTMLInputElement).files;
    this.archive.set(files && files.length ? files[0] : null);
  }

  protected upload(): void {
    const archive = this.archive();
    const name = this.name().trim();
    if (!archive || name.length < 3) {
      this.uploadError.set(
        'Give the project a name of at least 3 characters and choose a .zip file.',
      );
      return;
    }
    this.uploading.set(true);
    this.uploadError.set(null);
    this.projectsService.create(name, archive).subscribe({
      next: (project) => {
        this.uploading.set(false);
        this.created.set(project);
        this.load();
      },
      error: (error: unknown) => {
        this.uploading.set(false);
        this.uploadError.set(describeError(error));
      },
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.projectsService.list().subscribe({
      next: (page) => this.state.set({ kind: 'ready', projects: page.items }),
      error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
    });
  }
}
