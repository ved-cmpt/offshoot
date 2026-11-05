import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { JobProgress } from './job-progress';
import { makeJob } from './testing';
import { JOB_POLL_INTERVAL_MS, Job, describeJobError } from './workbench.service';

@Component({
  imports: [JobProgress],
  template: `<app-job-progress label="Analysis" [start]="job()" (finished)="done.push($event)" />`,
})
class Host {
  readonly job = signal<Job>(makeJob());
  readonly done: Job[] = [];
}

describe('JobProgress', () => {
  let fixture: ComponentFixture<Host>;
  let http: HttpTestingController;
  let page: HTMLElement;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      imports: [Host],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: JOB_POLL_INTERVAL_MS, useValue: 1000 },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Host);
    page = fixture.nativeElement;
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function tick(ms: number): void {
    vi.advanceTimersByTime(ms);
    fixture.detectChanges();
  }

  it('polls until the job finishes, then stops and reports it', () => {
    fixture.detectChanges();
    tick(0);
    expect(page.textContent).toContain('Analysis:');
    expect(page.textContent).toContain('Waiting to start');
    http
      .expectOne('/api/v1/jobs/j1')
      .flush(makeJob({ status: 'RUNNING', metrics: { stage: 'parsing' } }));
    fixture.detectChanges();
    expect(page.textContent).toContain('Running');
    expect(page.textContent).toContain('parsing');

    tick(1000);
    http.expectOne('/api/v1/jobs/j1').flush(makeJob({ status: 'SUCCEEDED' }));
    fixture.detectChanges();
    expect(page.textContent).toContain('Finished');
    expect(fixture.componentInstance.done.map((job) => job.status)).toEqual(['SUCCEEDED']);

    tick(5000);
    http.expectNone('/api/v1/jobs/j1');
  });

  it('never polls a job that has already finished', () => {
    fixture.componentInstance.job.set(makeJob({ status: 'SUCCEEDED', deduplicated: true }));
    fixture.detectChanges();
    tick(3000);
    http.expectNone('/api/v1/jobs/j1');
    expect(page.textContent).toContain('Nothing has changed');
    expect(fixture.componentInstance.done).toHaveLength(1);
  });

  it('says what a failure means, in words and with its code', () => {
    fixture.detectChanges();
    tick(0);
    http
      .expectOne('/api/v1/jobs/j1')
      .flush(makeJob({ status: 'FAILED', error_code: 'AI_RATE_LIMITED' }));
    fixture.detectChanges();
    expect(page.textContent).toContain('Failed');
    expect(page.textContent).toContain('rate limiting');
    expect(page.textContent).toContain('AI_RATE_LIMITED');
  });

  it('offers a way to resume when the check itself fails', () => {
    fixture.detectChanges();
    tick(0);
    http.expectOne('/api/v1/jobs/j1').flush({}, { status: 500, statusText: 'Error' });
    fixture.detectChanges();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('could not be checked');
    alert.querySelector('button')!.click();
    tick(0);
    http.expectOne('/api/v1/jobs/j1').flush(makeJob({ status: 'SUCCEEDED' }));
    fixture.detectChanges();
    expect(page.querySelector('[role="alert"]')).toBeNull();
    expect(page.textContent).toContain('Finished');
  });

  it('stops polling when it leaves the page', () => {
    fixture.detectChanges();
    tick(0);
    http.expectOne('/api/v1/jobs/j1').flush(makeJob({ status: 'RUNNING' }));
    fixture.destroy();
    vi.advanceTimersByTime(5000);
    http.expectNone('/api/v1/jobs/j1');
  });

  it('has a safe fallback for an unknown code', () => {
    expect(describeJobError('SOMETHING_NEW')).toContain('failed unexpectedly');
    expect(describeJobError(null)).toContain('failed unexpectedly');
  });
});
