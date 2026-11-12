import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { CodeView } from './code-view';
import { cobolLine, csharpLine, highlightLines, languageOf } from './highlight';

const kinds = (tokens: { kind: string; text: string }[]) =>
  tokens.filter((t) => t.text.trim()).map((t) => `${t.kind}:${t.text.trim()}`);

describe('syntax colouring', () => {
  it('reads a COBOL comment line from column 7', () => {
    expect(cobolLine('      * ROUNDED MEANS HALF-UP HERE')).toEqual([
      { kind: 'comment', text: '      * ROUNDED MEANS HALF-UP HERE' },
    ]);
  });

  it('colours COBOL keywords, names, pictures, levels and decimals', () => {
    expect(kinds(cobolLine('           COMPUTE RC-OUT-ENERGY ROUNDED ='))).toEqual([
      'keyword:COMPUTE',
      'plain:RC-OUT-ENERGY',
      'keyword:ROUNDED',
      'punct:=',
    ]);
    expect(kinds(cobolLine('           05  RT-RES-TIER1-RATE       PIC 9(5)V9(4) VALUE 0.0912.'))).toEqual([
      'level:05',
      'plain:RT-RES-TIER1-RATE',
      'keyword:PIC',
      'type:9(5)V9(4)',
      'keyword:VALUE',
      'number:0.0912',
      'punct:.',
    ]);
    expect(kinds(cobolLine('       5000-PRICE-ENERGY.'))[0]).toBe('type:5000-PRICE-ENERGY');
  });

  it('keeps every character of the line, in order', () => {
    const line = "           MOVE 'Y' TO RC-OUT-MIN-FLAG   *> inline";
    expect(cobolLine(line).map((t) => t.text).join('')).toBe(line);
    const cs = 'var energy = RoundToCent((t1 * 0.0912m) + x); // note';
    expect(csharpLine(cs, false).tokens.map((t) => t.text).join('')).toBe(cs);
  });

  it('colours C# keywords, types, strings, numbers and comments, across lines', () => {
    expect(kinds(csharpLine('public static decimal RoundToCent(decimal amount) => Math.Round(amount, 2);', false).tokens)).toContain(
      'type:RoundToCent',
    );
    expect(kinds(csharpLine('Assert.Equal(0.21m, "x");', false).tokens)).toEqual(
      expect.arrayContaining(['number:0.21m', 'string:"x"']),
    );
    const lines = highlightLines(['/* start', 'still comment */ int x = 1;'], 'csharp');
    expect(lines[0]).toEqual([{ kind: 'comment', text: '/* start' }]);
    expect(kinds(lines[1])).toEqual(['comment:still comment */', 'keyword:int', 'plain:x', 'punct:=', 'number:1', 'punct:;']);
  });

  it('picks the language from the file name', () => {
    expect(languageOf('RATECALC.cbl')).toBe('cobol');
    expect(languageOf('copy/RATES.cpy')).toBe('cobol');
    expect(languageOf('src/RateCalculator.cs')).toBe('csharp');
    expect(languageOf('README.txt')).toBe('plain');
  });
});

describe('CodeView', () => {
  it('renders source as text, never as markup, with marks and notes', async () => {
    const fixture = TestBed.createComponent(CodeView);
    fixture.componentRef.setInput('lines', ['// <img src=x onerror=alert(1)>', 'int a = 1;']);
    fixture.componentRef.setInput('language', 'csharp');
    fixture.componentRef.setInput('label', 'Sample');
    fixture.componentRef.setInput('start', 10);
    fixture.componentRef.setInput('marks', { 11: 'danger' });
    fixture.componentRef.setInput('notes', { 11: 'differs' });
    fixture.detectChanges();
    await fixture.whenStable();
    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent).toContain('<img src=x onerror=alert(1)>');
    const lines = host.querySelectorAll('.code__line');
    expect(lines[0].querySelector('.code__ln')?.textContent).toBe('10');
    expect(lines[1].classList).toContain('code__line--danger');
    expect(lines[1].textContent).toContain('differs');
    const region = host.querySelector('[role="region"]')!;
    expect(region.getAttribute('aria-label')).toBe('Sample');
    expect(region.getAttribute('tabindex')).toBe('0');
  });
});
