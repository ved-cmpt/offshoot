import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { describeError } from '../../core/api/api-error';
import { Project, ProjectsService } from './projects.service';

type ListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; projects: Project[] };

const STATUS_LABELS: Record<Project['status'], string> = {
  IMPORTED: 'Imported, not analyzed yet',
  ANALYZING: 'Analyzing',
  ANALYZED: 'Analyzed',
  FAILED: 'Analysis failed',
};

const SOURCE_LABELS: Record<Project['source_kind'], string> = {
  BUNDLED: 'Bundled sample',
  UPLOAD: 'Uploaded',
};

@Component({
  selector: 'app-projects',
  imports: [DatePipe, DecimalPipe, RouterLink],
  templateUrl: './projects.html',
  styleUrl: './projects.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Projects implements OnInit {
  private readonly projectsService = inject(ProjectsService);

  protected readonly state = signal<ListState>({ kind: 'loading' });
  protected readonly statusLabels = STATUS_LABELS;
  protected readonly sourceLabels = SOURCE_LABELS;

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.projectsService.list().subscribe({
      next: (page) => this.state.set({ kind: 'ready', projects: page.items }),
      error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
    });
  }
}
