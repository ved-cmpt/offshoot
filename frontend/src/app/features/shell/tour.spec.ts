import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ToastService, Toasts } from '../../shared/toast/toast';
import { actionKind } from '../audit/audit';
import { outcomeTone } from '../overview/overview';
import { TOUR_KEY, TOUR_STEPS, Tour, TourService } from './tour';

describe('TourService', () => {
  let navigate: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  });

  it('walks the rounding story by name-based links, and remembers that it ended', async () => {
    const tour = TestBed.inject(TourService);
    expect(tour.done()).toBe(false);
    tour.start();
    expect(tour.step()).toBe(0);
    expect(navigate).not.toHaveBeenCalled();
    tour.next();
    await Promise.resolve();
    expect(navigate).toHaveBeenCalledWith('/app/open/overview');
    tour.next();
    await Promise.resolve();
    expect(navigate).toHaveBeenCalledWith('/app/open/module/RATECALC');
    tour.back();
    expect(tour.step()).toBe(1);
    tour.end();
    expect(tour.step()).toBeNull();
    expect(localStorage.getItem(TOUR_KEY)).toBe('1');
    expect(tour.done()).toBe(true);
  });

  it('finishes after the last step', () => {
    const tour = TestBed.inject(TourService);
    tour.start();
    TOUR_STEPS.forEach(() => tour.next());
    expect(tour.step()).toBeNull();
    expect(tour.done()).toBe(true);
  });

  it('shows the step as a labelled, non-modal dialog with its controls', async () => {
    const fixture = TestBed.createComponent(Tour);
    TestBed.inject(TourService).start();
    fixture.detectChanges();
    await fixture.whenStable();
    const dialog = fixture.nativeElement.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.getAttribute('aria-modal')).toBe('false');
    expect(dialog.querySelector('#tour-title')?.textContent).toBe('Welcome to the live demo');
    const labels = Array.from(dialog.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(labels).toEqual(['Skip', 'Start the tour']);
  });
});

describe('Toasts', () => {
  afterEach(() => vi.useRealTimers());

  it('announces politely, keeps at most four and dismisses itself', () => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({});
    const fixture = TestBed.createComponent(Toasts);
    const service = TestBed.inject(ToastService);
    for (let i = 1; i <= 5; i++) {
      service.ok(`Saved ${i}`);
    }
    fixture.detectChanges();
    const region = fixture.nativeElement.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(region.querySelectorAll('.toast')).toHaveLength(4);
    expect(region.textContent).toContain('Saved 5');
    expect(region.textContent).not.toContain('Saved 1');
    vi.advanceTimersByTime(5001);
    fixture.detectChanges();
    expect(region.querySelectorAll('.toast')).toHaveLength(0);
  });
});

describe('status helpers', () => {
  it('gives audit actions a category and an icon by prefix', () => {
    expect(actionKind('module.approved')).toEqual({ tone: 'ok', icon: 'blocks' });
    expect(actionKind('ai.call').tone).toBe('violet');
    expect(actionKind('something.else').tone).toBe('neutral');
  });

  it('reads outcomes as good, bad, in progress or neutral', () => {
    expect(outcomeTone('succeeded')).toBe('good');
    expect(outcomeTone('APPROVED')).toBe('good');
    expect(outcomeTone('failed')).toBe('bad');
    expect(outcomeTone('running')).toBe('warn');
    expect(outcomeTone('recorded')).toBe('neutral');
  });
});
