import { DestroyRef, Directive, ElementRef, OnInit, inject } from '@angular/core';

/**
 * Adds `is-visible` once the element scrolls into view, so `.reveal` content fades in. Content is
 * in the page either way; without IntersectionObserver, or with reduced motion, it shows at once.
 */
@Directive({
  selector: '[appReveal]',
  host: { class: 'reveal' },
})
export class Reveal implements OnInit {
  private readonly element = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    const node: HTMLElement = this.element.nativeElement;
    const view = node.ownerDocument.defaultView;
    const still = view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (still || typeof IntersectionObserver === 'undefined') {
      node.classList.add('is-visible');
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          node.classList.add('is-visible');
          observer.disconnect();
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.05 },
    );
    observer.observe(node);
    this.destroyRef.onDestroy(() => observer.disconnect());
  }
}
