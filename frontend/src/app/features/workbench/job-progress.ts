import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { Job, WorkbenchService, describeJobError, isJobFinished } from './workbench.service';

const STATUS_TEXT: Record<Job['status'], string> = {
  QUEUED: 'Waiting to start',
  RUNNING: 'Running',
  SUCCEEDED: 'Finished',
  FAILED: 'Failed',
};

/** Live status of one job. Polls until it finishes, and always says what happened in words. */
@Component({
  selector: 'app-job-progress',
  template: `
    @if (current(); as job) {
      <div class="job" [class.job--failed]="job.status === 'FAILED'" role="status">
        <p>
          <strong>{{ label() }}:</strong> {{ statusText() }}
          @if (stage(); as text) {
            ({{ text }})
          }
        </p>
        @if (job.deduplicated && job.status === 'SUCCEEDED') {
          <p class="job__note">
            Nothing has changed since this last ran, so the earlier result still stands.
          </p>
        }
        @if (job.status === 'FAILED') {
          <p>
            {{ errorText() }} <span class="job__code">Code: {{ job.error_code }}</span>
          </p>
        }
      </div>
    }
    @if (pollError(); as message) {
      <div class="job job--failed" role="alert">
        <p>The job's progress could not be checked. {{ message }}</p>
        <button class="button button--quiet" type="button" (click)="resume()">Check again</button>
      </div>
    }
  `,
  styles: `
    .job {
      margin-block: var(--space-3);
      padding: var(--space-3) var(--space-4);
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
      background: var(--color-surface-raised);
    }

    .job--failed {
      border-color: var(--color-danger);
      background: var(--color-danger-bg);
    }

    .job__note,
    .job__code {
      color: var(--color-text-muted);
      font-size: var(--text-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobProgress {
  private readonly workbench = inject(WorkbenchService);
  private subscription: Subscription | null = null;

  readonly start = input.required<Job>();
  readonly label = input('Job');
  readonly finished = output<Job>();

  protected readonly current = signal<Job | null>(null);
  protected readonly pollError = signal<string | null>(null);
  protected readonly statusText = computed(() => {
    const job = this.current();
    return job ? STATUS_TEXT[job.status] : '';
  });
  protected readonly stage = computed(() => {
    const job = this.current();
    const stage = job?.metrics['stage'];
    return job?.status === 'RUNNING' && typeof stage === 'string' ? stage : null;
  });
  protected readonly errorText = computed(() =>
    describeJobError(this.current()?.error_code ?? null),
  );

  constructor() {
    effect((onCleanup) => {
      const job = this.start();
      untracked(() => this.follow(job));
      onCleanup(() => this.subscription?.unsubscribe());
    });
  }

  protected resume(): void {
    const job = this.current();
    if (job) {
      this.follow(job);
    }
  }

  private follow(job: Job): void {
    this.subscription?.unsubscribe();
    this.pollError.set(null);
    this.current.set(job);
    if (isJobFinished(job)) {
      this.finished.emit(job);
      return;
    }
    this.subscription = this.workbench.pollJob(job.id).subscribe({
      next: (latest) => {
        this.current.set({ ...latest, deduplicated: job.deduplicated });
        if (isJobFinished(latest)) {
          this.finished.emit(latest);
        }
      },
      error: (error: unknown) => this.pollError.set(describeError(error)),
    });
  }
}
